from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from pixel_workbench.model import Document, PixelError
from pixel_workbench.projects import frame_at
from pixel_workbench.service import DocumentService


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.service=DocumentService(Document(16,24,'Idle'),workspace=self.root/'work',runtime=self.root/'data')

    def call(self,action,**fields):
        return self.service.projects_action(dict(action=action,expected_document_id=self.service.doc.id,
                                                expected_revision=self.service.doc.revision,**fields))

    def paint(self,color=7):
        self.service.doc.apply([{'op':'pixel','x':2,'y':3,'color':color}])

    def test_fork_saves_unsaved_original_and_new_identity_without_overwrite(self):
        self.paint()
        original=self.service.doc.id
        color=self.service.doc.composite().getpixel((2,3))
        result=self.call('fork',name='Walk')
        self.assertEqual([p['number'] for p in result['projects']],[1,2])
        self.assertEqual(result['projects'][0]['document_id'],original)
        self.assertNotEqual(self.service.doc.id,original)
        first=Path(result['projects'][0]['path'])
        before=first.read_bytes()
        self.paint(8)
        self.service.save_project()
        self.assertEqual(first.read_bytes(),before)
        self.call('switch',project_id=result['projects'][0]['id'])
        self.assertEqual(self.service.doc.composite().getpixel((2,3)),color)
        self.assertEqual(self.service.doc.name,'Idle')

    def test_switch_checkpoints_dirty_project_and_library_survives_restart(self):
        first=self.call('fork',name='Walk')['projects'][0]
        second=self.service.projects.by_path(self.service.path)
        self.paint()
        self.call('switch',project_id=first['id'])
        restored=DocumentService(workspace=self.service.workspace,runtime=self.service.runtime)
        self.assertEqual(len(restored.projects.entries),2)
        restored.projects_action(dict(action='switch',project_id=second['id'],expected_document_id=restored.doc.id,
                                     expected_revision=restored.doc.revision))
        self.assertNotEqual(restored.doc.composite().getpixel((2,3))[3],0)

    def test_saved_versions_restore_into_new_project(self):
        self.service.checkpoint_current()
        original=self.service.projects.by_path(self.service.path)
        self.paint()
        self.service.save_project()
        current=Path(self.service.path).read_bytes()
        versions=self.call('versions',project_id=original['id'])['versions']
        self.assertEqual(len(versions),2)
        self.call('restore',project_id=original['id'],version_id=versions[-1]['id'],name='Restored idle')
        self.assertNotEqual(self.service.path,Path(original['path']))
        self.assertEqual(Path(original['path']).read_bytes(),current)
        self.assertEqual(self.service.doc.composite().getpixel((2,3))[3],0)
        self.assertNotEqual(self.service.doc.id,original['document_id'])

    def test_backup_failure_prevents_save_overwrite(self):
        self.service.checkpoint_current()
        target=self.service.path
        before=target.read_bytes()
        self.paint()
        with patch.object(self.service.projects,'backup',side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):self.service.save_project()
        self.assertEqual(target.read_bytes(),before)
        self.assertTrue(self.service.dirty)

    def test_register_cannot_hide_external_changes_to_active_file(self):
        self.service.checkpoint_current()
        changed=Document.open(self.service.path)
        changed.name='External edit'
        changed.save(self.service.path)
        with self.assertRaises(PixelError) as exc:self.call('register',path=str(self.service.path))
        self.assertEqual(exc.exception.code,'PROJECT_FILE_CHANGED')

    def test_external_file_change_prevents_silent_overwrite(self):
        self.service.checkpoint_current()
        target=self.service.path
        changed=Document.open(target)
        changed.name='External edit'
        changed.save(target)
        before=target.read_bytes()
        self.paint()
        with self.assertRaises(PixelError) as exc:self.service.save_project()
        self.assertEqual(exc.exception.code,'PROJECT_FILE_CHANGED')
        self.assertEqual(target.read_bytes(),before)

    def test_missing_switch_target_preserves_unsaved_current(self):
        entries=self.call('fork',name='Walk')['projects']
        Path(entries[0]['path']).unlink()
        self.paint()
        before=self.service.doc.to_dict()
        with self.assertRaises(OSError):self.call('switch',project_id=entries[0]['id'])
        self.assertEqual(self.service.doc.to_dict(),before)
        self.assertTrue(self.service.dirty)

    def test_fork_collision_and_stale_tokens_preserve_original(self):
        self.service.checkpoint_current()
        original=self.service.doc.id
        with self.assertRaises(PixelError):self.call('fork',path=str(self.service.path))
        self.assertEqual(self.service.doc.id,original)
        with self.assertRaises(PixelError):
            self.service.projects_action(dict(action='fork',expected_revision=-1,expected_document_id=original))
        self.assertEqual(len(self.service.projects.entries),1)

    def test_compare_is_read_only_and_includes_active_unsaved_pixels(self):
        self.paint()
        entries=self.call('fork',name='Walk')['projects']
        self.paint(8)
        before=self.service.doc.to_dict()
        files={p:p.read_bytes() for p in self.service.workspace.rglob('*.pixloom')}
        ids=[p['id'] for p in entries]
        result=self.call('compare',project_ids=ids,view='time',time_ms=150)
        self.assertEqual(len(result['images_png']),2)
        self.assertTrue(result['projects'][1]['current_unsaved'])
        self.assertEqual(result['projects'][1]['frames'],[0])
        self.assertEqual(self.service.doc.to_dict(),before)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in files.items()))

    def test_real_duration_and_paged_comparisons(self):
        self.service.doc.apply([{'op':'frame_add'} for _ in range(9)]+[{'op':'frame_set','frame':0,'duration_ms':200}])
        entries=self.call('fork',name='Walk')['projects']
        self.assertEqual(frame_at(self.service.doc,199),0)
        self.assertEqual(frame_at(self.service.doc,200),1)
        result=self.call('compare',project_ids=[p['id'] for p in entries],page=1)
        self.assertEqual(result['pages'],2)
        self.assertEqual(result['projects'][0]['frames'],[8,9])

    def test_version_id_cannot_escape_history_directory(self):
        self.service.checkpoint_current()
        entry=self.service.projects.by_path(self.service.path)
        with self.assertRaises(PixelError):self.call('restore',project_id=entry['id'],version_id='../../other')

    def test_remove_inactive_preserves_files_history_and_dirty_active(self):
        first=self.call('fork',name='Walk')['projects'][0]
        path=Path(first['path'])
        before=path.read_bytes()
        self.paint()
        current=self.service.doc.to_dict()
        self.call('remove',project_id=first['id'])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.service.doc.to_dict(),current)
        self.assertTrue(self.service.dirty)
        self.assertEqual(len(self.call('list')['projects']),1)
        self.assertEqual(self.call('deleted')['projects'][0]['id'],first['id'])
        with self.assertRaises(PixelError):self.call('switch',project_id=first['id'])
        restored=self.call('undelete',project_id=first['id'])['projects'][0]
        self.assertEqual(restored['id'],first['id'])
        self.assertEqual(restored['number'],1)

    def test_remove_active_saves_dirty_pixels_and_switches_then_restores(self):
        first=self.call('fork',name='Walk')['projects'][0]
        active=dict(self.service.projects.by_path(self.service.path))
        self.paint()
        self.call('remove',project_id=active['id'])
        self.assertEqual(self.service.doc.id,first['document_id'])
        self.assertTrue(Document.open(active['path']).composite().getpixel((2,3))[3])
        self.call('undelete',project_id=active['id'])
        self.assertTrue(self.call('versions',project_id=active['id'])['versions'])
        self.call('switch',project_id=active['id'])
        self.assertTrue(self.service.doc.composite().getpixel((2,3))[3])

    def test_remove_all_leaves_empty_shelf_and_no_startup_path(self):
        entries=self.call('fork',name='Walk')['projects']
        removed=self.call('remove',project_ids=[entry['id'] for entry in entries])
        self.assertFalse(removed['projects'])
        self.assertIsNone(self.service.path)
        self.assertFalse(self.service.dirty)
        self.assertIsNone(json.loads((self.service.runtime/'last-project.json').read_text(encoding='utf-8'))['path'])
        restart=DocumentService(workspace=self.service.workspace,runtime=self.service.runtime)
        self.assertEqual(len(restart.projects.listing()),0)
        self.assertEqual(len(restart.projects.listing(deleted=True)),2)
        self.call('new',name='New after deletion')
        self.assertEqual(self.service.projects.by_path(self.service.path)['number'],3)

    def test_invalid_batch_remove_does_not_remove_any_project(self):
        entries=self.call('fork',name='Walk')['projects']
        before=self.service.doc.to_dict()
        with self.assertRaises(PixelError):self.call('remove',project_ids=[entries[0]['id'],'missing'])
        self.assertEqual(len(self.call('list')['projects']),2)
        self.assertEqual(self.service.doc.to_dict(),before)

    def test_failed_catalog_write_rolls_back_deleted_flags(self):
        self.service.checkpoint_current()
        entry=self.service.projects.by_path(self.service.path)
        with patch.object(self.service.projects,'persist',side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):self.service.projects.set_deleted([entry['id']])
        self.assertEqual(len(self.service.projects.listing()),1)
        self.assertFalse(self.service.projects.listing(deleted=True))

    def test_adding_deleted_file_restores_same_identity(self):
        self.service.checkpoint_current()
        entry=dict(self.service.projects.by_path(self.service.path))
        self.call('remove',project_id=entry['id'])
        self.call('register',path=entry['path'])
        restored=self.call('list')['projects'][0]
        self.assertEqual(restored['id'],entry['id'])
        self.assertEqual(restored['number'],entry['number'])

    def test_close_hides_tab_without_touching_files_or_remove_list(self):
        first=self.call('fork',name='Walk')['projects'][0]
        path=Path(first['path'])
        before=path.read_bytes()
        closed=self.call('close',project_id=first['id'])
        self.assertEqual(closed['changed_project_ids'],[first['id']])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual([entry['id'] for entry in self.call('list')['projects']],[e['id'] for e in closed['projects'] if e['id']!=first['id']])
        self.assertEqual([entry['id'] for entry in self.call('closed')['projects']],[first['id']])
        self.assertFalse(self.call('deleted')['projects'])
        self.assertEqual(self.call('closed')['projects'][0]['closed'],True)

    def test_close_active_opens_right_neighbour_and_keeps_dirty_pixels(self):
        self.call('fork',name='Walk')
        self.call('fork',name='Attack')
        middle=self.call('list')['projects'][1]
        right=self.call('list')['projects'][2]
        self.call('switch',project_id=middle['id'])
        self.paint()
        closed=self.call('close',project_id=middle['id'])
        self.assertEqual(self.service.doc.id,right['document_id'])
        self.assertEqual(Path(self.service.path).resolve(),Path(right['path']).resolve())
        self.assertTrue(Document.open(middle['path']).composite().getpixel((2,3))[3])
        self.assertIn(middle['id'],closed['changed_project_ids'])
        self.assertIn(middle['id'],[entry['id'] for entry in self.call('closed')['projects']])

    def test_close_active_without_neighbour_leaves_clean_workspace(self):
        entry=self.service.checkpoint_current()
        self.assertEqual(self.call('list')['projects'][0]['id'],entry['id'])
        result=self.call('close',project_id=entry['id'])
        self.assertFalse(result['projects'])
        self.assertIsNone(self.service.path)
        self.assertFalse(self.service.dirty)
        self.assertTrue(Path(entry['path']).is_file())

    def test_close_active_finds_farther_valid_right_tab(self):
        for name in ('Walk','Attack','Dodge'):self.call('fork',name=name)
        entries=self.call('list')['projects']
        self.call('switch',project_id=entries[1]['id'])
        self.paint()
        Path(entries[0]['path']).unlink()
        Path(entries[2]['path']).write_text('corrupt fixture',encoding='utf-8')
        self.call('close',project_id=entries[1]['id'])
        self.assertEqual(self.service.doc.id,entries[3]['document_id'])
        self.assertTrue(Document.open(entries[1]['path']).composite().getpixel((2,3))[3])

    def test_close_active_finds_farther_valid_left_tab(self):
        for name in ('Walk','Attack','Dodge'):self.call('fork',name=name)
        entries=self.call('list')['projects']
        self.call('switch',project_id=entries[2]['id'])
        Path(entries[1]['path']).write_text('corrupt fixture',encoding='utf-8')
        Path(entries[3]['path']).unlink()
        self.call('close',project_id=entries[2]['id'])
        self.assertEqual(self.service.doc.id,entries[0]['document_id'])

    def test_close_prefers_explicit_surviving_tab_over_nearest_neighbour(self):
        for name in ('Walk','Attack'):self.call('fork',name=name)
        entries=self.call('list')['projects']
        self.call('switch',project_id=entries[1]['id'])
        result=self.call('close',project_id=entries[1]['id'],keep_project_id=entries[0]['id'])
        self.assertEqual(self.service.doc.id,entries[0]['document_id'])
        self.assertEqual(result['changed_project_ids'],[entries[1]['id']])
        self.assertTrue(Path(entries[1]['path']).is_file())

    def test_close_persists_across_restart_and_reopen_restores_same_identity(self):
        first=self.call('fork',name='Walk')['projects'][0]
        self.call('close',project_ids=[first['id']])
        restart=DocumentService(workspace=self.service.workspace,runtime=self.service.runtime)
        self.assertEqual(len(restart.projects.listing()),1)
        self.assertEqual([e['id'] for e in restart.projects.listing(closed=True)],[first['id']])
        reopened=restart.projects_action(dict(action='reopen',project_ids=[first['id']],
                                              expected_document_id=restart.doc.id,expected_revision=restart.doc.revision))
        self.assertEqual(reopened['changed_project_ids'],[first['id']])
        self.assertEqual([e['id'] for e in restart.projects.listing()],
                         [e['id'] for e in reopened['projects']])
        self.assertIn(first['id'],[e['id'] for e in restart.projects.listing()])
        self.assertFalse(restart.projects.listing(closed=True))
        self.assertEqual(restart.projects.by_path(first['path'])['number'],first['number'])

    def test_switching_to_a_closed_project_reopens_its_tab(self):
        first=self.call('fork',name='Walk')['projects'][0]
        active=self.service.projects.by_path(self.service.path)
        self.call('close',project_id=first['id'])
        self.assertEqual(len(self.call('list')['projects']),1)
        self.call('switch',project_id=first['id'])
        self.assertEqual(self.service.doc.id,first['document_id'])
        self.assertEqual(len(self.call('list')['projects']),2)
        self.assertFalse(self.call('closed')['projects'])
        self.assertEqual(self.service.projects.by_path(active['path'])['id'],active['id'])

    def test_remove_clears_the_closed_flag(self):
        first=self.call('fork',name='Walk')['projects'][0]
        self.call('close',project_id=first['id'])
        self.call('remove',project_id=first['id'])
        self.assertFalse(self.call('closed')['projects'])
        self.assertEqual([e['id'] for e in self.call('deleted')['projects']],[first['id']])
        self.call('undelete',project_id=first['id'])
        self.assertIn(first['id'],[e['id'] for e in self.call('list')['projects']])

    def test_close_rejects_unknown_ids_without_changing_tabs(self):
        first=self.call('fork',name='Walk')['projects'][0]
        before=self.service.projects.entries
        with self.assertRaises(PixelError):self.call('close',project_ids=[first['id'],'missing'])
        self.assertEqual(self.service.projects.entries,before)
        self.assertEqual(len(self.call('list')['projects']),2)

    def test_project_library_counts_separate_open_and_closed(self):
        first=self.call('fork',name='Walk')['projects'][0]
        self.call('close',project_id=first['id'])
        library=self.service.state()['project_library']
        self.assertEqual((library['count'],library['open_count'],library['closed_count'],library['deleted_count']),(2,1,1,0))
