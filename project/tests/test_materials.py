import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from PIL import Image

from pixel_workbench.materials import decode, normal_vectors, render, source_key
from pixel_workbench.model import Document, PixelError
from pixel_workbench.service import DocumentService
from pixel_workbench.quality import content_digest, scope_digest, review_scope


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.doc=Document(16,12,'Material fixture')
        self.doc.apply([{'op':'palette_set','colors':['#00000000','#ffffffff','#40508080','#ffb04080']},
                        {'op':'rect','x':2,'y':2,'width':10,'height':8,'color':1}])
        self.service=DocumentService(self.doc,workspace=self.root/'work',runtime=self.root/'data')

    def tearDown(self):self.temp.cleanup()

    def call(self,action,**fields):
        payload={'action':action,**fields}
        if action!='status':payload.update(expected_document_id=self.service.doc.id,expected_revision=self.service.doc.revision)
        return self.service.dispatch('POST','/material',{},payload)[0]

    def image(self,preview,role):
        index=preview['image_roles'].index(role)
        return Image.open(io.BytesIO(base64.b64decode(preview['images_png'][index]))).convert('RGBA')

    def map_file(self,name='normal.png',color=(255,128,128,255),size=None):
        path=self.root/name;Image.new('RGBA',size or (16,12),color).save(path);return str(path)

    def test_preview_changes_no_pixels_palette_history_dirty_or_files(self):
        before=self.doc.to_dict();undo=len(self.doc.undo_stack);dirty=self.service.dirty;files=set(self.root.rglob('*'))
        preview=self.call('preview',normal_source={'kind':'silhouette','bevel':2,'strength':4},view='normal',scale=1)
        self.assertEqual(self.doc.to_dict(),before);self.assertEqual(len(self.doc.undo_stack),undo)
        self.assertEqual(self.service.dirty,dirty);self.assertEqual(set(self.root.rglob('*')),files)
        self.assertEqual(preview['image_roles'],['normal_data','lighting_preview']);self.assertTrue(preview['approximate'])

    def test_apply_save_load_undo_redo_preserve_color_and_palette(self):
        pixels=self.doc.composite().tobytes();palette=self.doc.palette.copy();count=len(self.doc.undo_stack)
        preview=self.call('preview',normal_source={'kind':'flat'},settings={'intensity':2})
        self.call('apply',preview_id=preview['preview_id'])
        self.assertEqual(len(self.doc.undo_stack),count+1);self.assertTrue(self.service.dirty)
        self.assertEqual(self.doc.composite().tobytes(),pixels);self.assertEqual(self.doc.palette,palette)
        path=self.root/'saved.pixloom';self.doc.save(path);loaded=Document.open(path)
        self.assertEqual(loaded.material,self.doc.material);self.assertEqual(loaded.composite().tobytes(),pixels)
        self.assertTrue(self.doc.undo());self.assertIsNone(self.doc.material)
        self.assertTrue(self.doc.redo());self.assertEqual(self.doc.material['settings']['intensity'],2)
        self.call('clear');self.assertIsNone(self.doc.material);self.assertEqual(self.doc.composite().tobytes(),pixels)

    def test_reapplying_identical_material_adds_no_history_or_revision(self):
        p=self.call('preview');self.call('apply',preview_id=p['preview_id'])
        p=self.call('preview');revision=self.doc.revision;history=len(self.doc.undo_stack)
        self.call('apply',preview_id=p['preview_id'])
        self.assertEqual(self.doc.revision,revision);self.assertEqual(len(self.doc.undo_stack),history)

    def test_material_edits_do_not_invalidate_original_color_review_digest(self):
        old=content_digest(self.doc);scope=review_scope(self.doc);scoped=scope_digest(self.doc,scope)
        p=self.call('preview');self.call('apply',preview_id=p['preview_id'])
        self.assertEqual(content_digest(self.doc),old);self.assertEqual(scope_digest(self.doc,scope),scoped)

    def test_normal_brush_draft_continues_without_entering_color_palette(self):
        p=self.call('preview',view='normal',scale=1)
        p=self.call('preview',source_preview_id=p['preview_id'],normal_edits=[{'op':'rect','rect':[3,3,2,2],'normal':[1.,0.,0.]}],view='normal',scale=1)
        image=self.image(p,'normal_data');self.assertEqual(image.getpixel((3,3)),(255,128,128,255))
        p=self.call('preview',source_preview_id=p['preview_id'],settings={'intensity':2},view='normal',scale=1)
        self.assertEqual(self.image(p,'normal_data').getpixel((3,3)),(255,128,128,255))
        self.assertNotIn('#ff8080ff',self.doc.palette)
        self.call('apply',preview_id=p['preview_id']);self.assertTrue(self.doc.strict_palette)

    def test_invalid_brush_and_unknown_settings_leave_document_untouched(self):
        before=self.doc.to_dict()
        for args in [{'settings':{'made_up':1}}, {'settings':{'ambient':float('nan')}}, {'settings':{'intensity':True}},
                     {'normal_edits':[{'op':'rect','rect':[0,0,1,1],'normal':[0.,0.,0.]}]},
                     {'normal_edits':[{'op':'rect','rect':[15,11,2,2],'normal':[0.,0.,1.]}]},
                     {'normal_source':{'kind':'flat','path':'ignored.png'}}]:
            with self.subTest(args=args),self.assertRaises(PixelError):self.call('preview',**args)
            self.assertEqual(self.doc.to_dict(),before)
        with self.assertRaises(PixelError):self.call('apply',settings={'ambient':1})

    def test_stale_and_other_document_preview_never_apply_or_export(self):
        p=self.call('preview');self.doc.apply([{'op':'pixel','x':0,'y':0,'color':1}]);before=self.doc.to_dict()
        for action,fields in [('apply',{}),('export',{'path':str(self.root/'stale.png')})]:
            with self.assertRaises(PixelError) as error:self.call(action,preview_id=p['preview_id'],**fields)
            self.assertEqual(error.exception.code,'MATERIAL_PREVIEW_STALE')
        self.assertEqual(self.doc.to_dict(),before);self.assertFalse((self.root/'stale.png').exists())
        self.service.doc=Document(16,12)
        with self.assertRaises(PixelError):self.call('apply',preview_id=p['preview_id'])

    def test_wrong_dimensions_and_sheet_frame_counts_are_explicit(self):
        path=self.map_file(size=(8,8))
        with self.assertRaises(PixelError):self.call('preview',normal_source={'kind':'import','path':path})
        self.doc.apply([{'op':'frame_add'}])
        path=self.map_file(name='sheet.png',size=(32,12))
        p=self.call('preview',normal_source={'kind':'import','path':path,'frames':2,'columns':2},view='normal',scale=1)
        self.assertEqual(p['normal_frames'],2)
        with self.assertRaises(PixelError):self.call('preview',normal_source={'kind':'import','path':path,'frames':3})

    def test_frame_specific_edit_and_shared_to_per_frame_mapping(self):
        self.doc.apply([{'op':'frame_add'}])
        p=self.call('preview',normal_source={'kind':'flat','frames':2},normal_edits=[{'op':'rect','frame':1,'rect':[3,3,1,1],'normal':[1.,0.,0.]}],frame=1,view='normal',scale=1)
        self.assertEqual(self.image(p,'normal_data').getpixel((3,3)),(255,128,128,255))
        p=self.call('preview',source_preview_id=p['preview_id'],frame=0,view='normal',scale=1)
        self.assertEqual(self.image(p,'normal_data').getpixel((3,3)),(128,128,255,255))
        p=self.call('preview',source_preview_id=p['preview_id'],normal_source={'kind':'current','frames':1},frame=1)
        self.assertEqual(p['normal_frames'],1)
        p=self.call('preview',source_preview_id=p['preview_id'],normal_source={'kind':'current','frames':2})
        self.assertEqual(p['normal_frames'],2)

    def test_geometry_changes_preserve_maps_but_report_invalid_binding(self):
        p=self.call('preview');self.call('apply',preview_id=p['preview_id']);saved=deepcopy(self.doc.material)
        self.doc.apply([{'op':'canvas_resize','width':18,'height':12}])
        self.assertEqual(self.doc.material,saved)
        self.assertIn('MATERIAL_SIZE_MISMATCH',[w['code'] for w in self.call('status')['warnings']])
        self.doc.save(self.root/'resized.pixloom');Document.open(self.root/'resized.pixloom')
        with self.assertRaises(PixelError):self.call('preview')
        self.call('preview',normal_source={'kind':'flat'})

    def test_changed_art_warns_and_bad_frame_binding_does_not_corrupt_legacy_pixels(self):
        self.doc.apply([{'op':'frame_add'}]);p=self.call('preview',normal_source={'kind':'flat','frames':2})
        self.call('apply',preview_id=p['preview_id']);self.doc.apply([{'op':'frame_add'}])
        self.assertIn('MATERIAL_FRAME_MISMATCH',[w['code'] for w in self.call('status')['warnings']])
        with self.assertRaises(PixelError):self.call('preview')
        self.assertEqual(len(Document.from_dict(self.doc.to_dict()).durations),3)

    def test_light_direction_and_green_up_convention_are_measurable(self):
        path=self.map_file(color=(255,128,128,255))
        common={'ambient':0.,'intensity':1.,'light_radius':8.,'light_height':.01,'specular':0.,'light_color':'#ffffff'}
        right=self.call('preview',normal_source={'kind':'import','path':path},settings={**common,'light_x':2.},view='render',scale=1)
        left=self.call('preview',normal_source={'kind':'import','path':path},settings={**common,'light_x':-1.},view='render',scale=1)
        self.assertGreater(self.image(right,'lighting_preview').getpixel((6,6))[0],200)
        self.assertEqual(self.image(left,'lighting_preview').getpixel((6,6))[0],0)
        path=self.map_file(name='up.png',color=(128,255,128,255))
        up=self.call('preview',normal_source={'kind':'import','path':path},settings={**common,'light_y':-1.},view='render',scale=1)
        flipped=self.call('preview',normal_source={'kind':'import','path':path},settings={**common,'light_y':-1.,'flip_y':True},view='render',scale=1)
        self.assertGreater(self.image(up,'lighting_preview').getpixel((6,6))[0],200)
        self.assertEqual(self.image(flipped,'lighting_preview').getpixel((6,6))[0],0)

    def test_alpha_and_emission_layer_occlusion_are_preserved(self):
        base=self.doc.layers[0].id
        self.doc.apply([{'op':'layer_add','id':'glow','name':'glow'}, {'op':'rect','x':0,'y':0,'width':14,'height':11,'color':3},
                        {'op':'layer_move','layer':'glow','index':0}])
        p=self.call('preview',settings={'ambient':0.,'intensity':0.,'specular':0.,'emission_layers':['glow']},view='render',scale=1)
        result=self.image(p,'lighting_preview')
        # Background display is separate from the raw render alpha.
        ticket=self.service.materials.ticket(self.doc,p['preview_id']);raw=render(self.doc,ticket['material'],0)
        self.assertEqual(raw.getchannel('A').tobytes(),self.doc.composite().getchannel('A').tobytes())
        self.assertEqual(raw.getpixel((5,5))[:3],(0,0,0))  # opaque upper metal occludes lower glow
        self.assertGreater(raw.getpixel((0,0))[0],0)

    def test_identity_light_settings_return_exact_original_composite(self):
        p=self.call('preview',settings={'ambient':1.,'intensity':0.,'emission_strength':1.},view='render',scale=1)
        raw=render(self.doc,self.service.materials.ticket(self.doc,p['preview_id'])['material'],0)
        self.assertEqual(raw.tobytes(),self.doc.composite().tobytes())

    def test_conditional_images_and_tiny_canvases(self):
        p=self.call('preview');same=self.call('preview',if_image_key=p['image_key'])
        self.assertTrue(same['unchanged']);self.assertNotIn('images_png',same)
        changed=self.call('preview',if_image_key=p['image_key'],settings={'intensity':2})
        self.assertFalse(changed['unchanged'])
        self.service.doc=Document(1,1)
        p=self.call('preview',normal_source={'kind':'silhouette'})
        self.assertEqual(p['normal_frames'],1)

    def test_exports_use_preview_frame_not_active_frame_and_never_claim_lighting_review(self):
        self.doc.apply([{'op':'frame_add'},{'op':'clear','frame':1}])
        p=self.call('preview',frame=1)
        exported=self.call('export',preview_id=p['preview_id'],path=str(self.root/'frame.png'),kind='render')
        self.assertEqual(exported['frames'],[1]);self.assertEqual(exported['delivery_status'],'material_preview')
        with Image.open(exported['path']) as image:self.assertIsNone(image.getbbox())
        with self.assertRaises(PixelError):self.call('export',preview_id=p['preview_id'],path=exported['path'])

    def test_zip_maps_are_aligned_and_preserve_unequal_source_timing(self):
        self.doc.apply([{'op':'frame_set','frame':0,'duration_ms':70},{'op':'frame_add','duration_ms':130}])
        p=self.call('preview',normal_source={'kind':'silhouette'})
        result=self.call('export',preview_id=p['preview_id'],path=str(self.root/'material.zip'),kind='bundle',all_frames=True,columns=2)
        with zipfile.ZipFile(result['path']) as archive:
            info=json.loads(archive.read('frames.json'));self.assertEqual([f['duration_ms'] for f in info['frames']],[70,130])
            self.assertEqual([f['x'] for f in info['frames']],[0,16])
            for name in ('color.png','normal.png','specular.png','emission.png'):
                with Image.open(io.BytesIO(archive.read(name))) as image:self.assertEqual(image.size,(32,12))
            self.assertIn('normal_texture = ExtResource',archive.read('material.tres').decode())
        result=self.call('export',preview_id=p['preview_id'],path=str(self.root/'sheet.zip'),kind='sheet',all_frames=True)
        with zipfile.ZipFile(result['path']) as archive:self.assertIn('render.png',archive.namelist())

    def test_corrupt_material_data_rejected_and_old_project_has_no_material(self):
        self.assertIsNone(Document.from_dict(self.doc.to_dict()).material)
        p=self.call('preview');self.call('apply',preview_id=p['preview_id'])
        data=self.doc.to_dict();data['material']['normal'][0]='bad-png'
        with self.assertRaises(PixelError):Document.from_dict(data)

    def test_color_image_mistaken_for_normal_and_back_facing_brush_are_rejected(self):
        path=self.map_file(color=(70,50,0,255));before=self.doc.to_dict()
        with self.assertRaises(PixelError) as error:self.call('preview',normal_source={'kind':'import','path':path})
        self.assertEqual(error.exception.code,'INVALID_NORMAL_MAP')
        with self.assertRaises(PixelError):self.call('preview',normal_edits=[{'op':'rect','rect':[0,0,1,1],'normal':[0.,0.,-1.]}])
        self.assertEqual(self.doc.to_dict(),before)

    def test_storage_failure_reports_committed_unsaved_material_without_false_rollback(self):
        preview=self.call('preview');pixels=self.doc.composite().tobytes()
        with patch.object(self.service,'autosave',side_effect=OSError('disk unavailable')):
            result=self.call('apply',preview_id=preview['preview_id'])
        self.assertTrue(result['applied']);self.assertTrue(result['unsaved_changes']);self.assertIn('storage_warning',result)
        self.assertIsNotNone(self.doc.material);self.assertEqual(self.doc.composite().tobytes(),pixels)
        self.doc.undo();self.assertIsNone(self.doc.material)

    def test_explicit_rebase_preserves_draft_but_cannot_cross_documents(self):
        preview=self.call('preview',normal_edits=[{'op':'rect','rect':[5,5,1,1],'normal':[1.,0.,0.]}])
        self.doc.apply([{'op':'pixel','x':0,'y':0,'color':1}])
        rebased=self.call('preview',source_preview_id=preview['preview_id'],rebase=True,view='normal',scale=1)
        self.assertTrue(rebased['alignment_warning']);self.assertEqual(self.image(rebased,'normal_data').getpixel((5,5)),(255,128,128,255))
        self.service.doc=Document(16,12)
        with self.assertRaises(PixelError):self.call('preview',source_preview_id=preview['preview_id'],rebase=True)

    def test_transparent_specular_mask_does_not_add_highlights(self):
        opaque=self.map_file(name='opaque-mask.png',color=(255,255,255,255))
        transparent=self.map_file(name='clear-mask.png',color=(255,255,255,0))
        values={'ambient':0.,'intensity':1.,'specular':1.,'shininess':1.,'light_color':'#ffffff'}
        a=self.call('preview',specular_path=opaque,settings=values,view='render',scale=1)
        b=self.call('preview',specular_path=transparent,settings=values,view='render',scale=1)
        self.assertGreater(sum(self.image(a,'lighting_preview').getpixel((6,6))[:3]),sum(self.image(b,'lighting_preview').getpixel((6,6))[:3]))

    def test_open_gui_draft_is_not_evicted_and_expired_maps_can_be_repreviewed(self):
        p=self.call('preview');key=p['preview_id'];self.service.materials.retain(key)
        for i in range(12):self.call('preview',settings={'intensity':i/10})
        self.assertIn(key,self.service.materials.previews)
        self.service.materials.previews[key]['created']-=1000
        with self.assertRaises(PixelError) as error:self.call('apply',preview_id=key)
        self.assertEqual(error.exception.code,'MATERIAL_PREVIEW_EXPIRED')
        fresh=self.call('preview',source_preview_id=key)
        self.call('apply',preview_id=fresh['preview_id']);self.assertIsNotNone(self.doc.material)
        self.service.materials.release(key)

    def test_fast_preview_does_not_resize_normal_edits_or_exports(self):
        self.service.doc=Document(300,150)
        p=self.call('preview',preview_limit=128,view='render',scale=1)
        self.assertTrue(p['preview_limited']);self.assertEqual(self.image(p,'lighting_preview').size,(128,64))
        result=self.call('export',preview_id=p['preview_id'],path=str(self.root/'full.png'))
        with Image.open(result['path']) as image:self.assertEqual(image.size,(300,150))
        p=self.call('preview',preview_limit=128,view='normal',scale=1)
        self.assertFalse(p['preview_limited']);self.assertEqual(self.image(p,'normal_data').size,(300,150))

    def test_unsupported_height_depth_is_rejected_without_silent_clipping(self):
        path=self.root/'height16.png';Image.new('I;16',(16,12),32000).save(path)
        before=self.doc.to_dict()
        with self.assertRaises(PixelError):self.call('preview',normal_source={'kind':'height','path':str(path)})
        self.assertEqual(self.doc.to_dict(),before)

    def test_oversized_embedded_map_and_save_do_not_replace_existing_artwork(self):
        p=self.call('preview');before=self.doc.to_dict();history=len(self.doc.undo_stack)
        base=len(json.dumps(before,ensure_ascii=False,separators=(',',':')).encode())
        with patch('pixel_workbench.model.MAX_PROJECT_BYTES',base+20):
            with self.assertRaises(PixelError):self.call('apply',preview_id=p['preview_id'])
        self.assertEqual(self.doc.to_dict(),before);self.assertEqual(len(self.doc.undo_stack),history)
        target=self.root/'safe.pixloom';self.doc.save(target);original=target.read_bytes()
        with patch('pixel_workbench.model.MAX_PROJECT_BYTES',10):
            with self.assertRaises(PixelError):self.doc.save(target)
        self.assertEqual(target.read_bytes(),original)

    def test_estimated_normal_remains_labeled_after_local_brush_adjustment(self):
        p=self.call('preview',normal_source={'kind':'silhouette'})
        changed=self.call('preview',source_preview_id=p['preview_id'],normal_edits=[{'op':'rect','rect':[4,4,2,2],'normal':[1.,0.,0.]}])
        self.assertTrue(changed['approximate']);self.assertEqual(changed['normal_origin'],'silhouette')
        self.call('apply',preview_id=changed['preview_id'])
        self.assertEqual(self.doc.material['normal_origin'],'silhouette')

    def test_unknown_emission_layer_is_not_silently_accepted(self):
        before=self.doc.to_dict()
        with self.assertRaises(PixelError):self.call('preview',settings={'emission_layers':['missing-layer']})
        self.assertEqual(self.doc.to_dict(),before)

    def test_exported_emission_respects_occlusion_strength_and_source_pixels(self):
        self.doc.apply([{'op':'layer_add','id':'glow','name':'glow'},
                        {'op':'rect','x':0,'y':0,'width':14,'height':11,'color':3},
                        {'op':'layer_move','layer':'glow','index':0}])
        before=self.doc.composite().tobytes()
        def exported(strength):
            p=self.call('preview',settings={'emission_layers':['glow'],'emission_strength':strength})
            path=self.root/f'emission-{strength}.zip'
            self.call('export',preview_id=p['preview_id'],path=str(path),kind='bundle')
            with zipfile.ZipFile(path) as archive:return Image.open(io.BytesIO(archive.read('emission.png'))).convert('RGBA')
        image=exported(1.)
        self.assertEqual(image.getpixel((5,5)),(0,0,0,0))
        self.assertGreater(image.getpixel((0,0))[0],0)
        self.assertEqual(exported(0.).getpixel((0,0))[:3],(0,0,0))
        self.assertEqual(self.doc.composite().tobytes(),before)


if __name__=='__main__':unittest.main()
