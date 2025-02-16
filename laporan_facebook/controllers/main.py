from odoo import http, fields
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import ValidationError, AccessError
import base64
import logging
import json
from datetime import datetime
import mimetypes
import math

_logger = logging.getLogger(__name__)

class LaporanPortal(CustomerPortal):
    
    def _prepare_home_portal_values(self, counters):
        """Menambahkan counter laporan ke portal home"""
        values = super()._prepare_home_portal_values(counters)
        if 'laporan_count' in counters:
            laporan_count = request.env['laporan.facebook'].search_count([
                ('created_user_id', '=', request.env.user.id)
            ])
            values['laporan_count'] = laporan_count
        return values

    def _get_file_type(self, filename):
        """Helper untuk menentukan tipe file dari ekstensi"""
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            if mime_type.startswith('image/'):
                return 'image'
            elif mime_type.startswith('video/'):
                return 'video'
            elif mime_type in ['application/pdf', 'application/msword', 
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                return 'document'
        return 'document'

    def _prepare_portal_layout_values(self):
        """Extends portal layout values"""
        values = super()._prepare_portal_layout_values()
        values['page_name'] = 'laporan'
        return values

    def _get_laporan_domain(self, search=None, kategori_id=None):
        """Build domain for laporan search"""
        domain = [('created_user_id', '=', request.env.user.id)]
        
        if search:
            domain += [
                '|', '|', '|', '|',
                ('kode_laporan', 'ilike', search),
                ('nama_akun', 'ilike', search),
                ('link_fb', 'ilike', search),
                ('deskripsi', 'ilike', search),
                ('tag_ids.nama', 'ilike', search)
            ]
            
        if kategori_id:
            domain += [('tag_ids.kategori_id', '=', int(kategori_id))]
            
        return domain

    @http.route(['/my/laporan', '/my/laporan/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_laporan(self, page=1, sortby=None, filterby=None, search=None, **kw):
        """Portal page for user's laporan"""
        values = self._prepare_portal_layout_values()
        Laporan = request.env['laporan.facebook']
        
        # Sorting
        sorting = {
            'date': {'label': 'Tanggal', 'order': 'tanggal_lapor desc'},
            'name': {'label': 'Kode', 'order': 'kode_laporan'},
            'status': {'label': 'Status', 'order': 'status'},
        }
        sort = sorting.get(sortby, sorting['date'])
        order = sort['order']
        
        # Domain
        domain = self._get_laporan_domain(search=search, kategori_id=kw.get('kategori_id'))
        
        # Paging
        laporan_count = Laporan.search_count(domain)
        pager = portal_pager(
            url="/my/laporan",
            url_args={'sortby': sortby, 'search': search, 'filterby': filterby},
            total=laporan_count,
            page=page,
            step=self._items_per_page
        )
        
        # Get records
        laporan = Laporan.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager['offset']
        )
        
        # Get categories for filter
        kategori = request.env['laporan.kategori'].search([('active', '=', True)])
        
        values.update({
            'laporan': laporan,
            'page_name': 'laporan',
            'default_url': '/my/laporan',
            'pager': pager,
            'sorting': sorting,
            'sortby': sortby,
            'filterby': filterby,
            'search': search,
            'kategori': kategori,
            'selected_kategori_id': int(kw.get('kategori_id', 0))
        })
        return request.render("laporan_facebook.portal_my_laporan", values)

    @http.route(['/laporan/create'], type='http', auth="user", website=True)
    def laporan_create(self, **kw):
        """Form untuk membuat laporan baru"""
        values = {
            'page_name': 'create_laporan',
            'error': {},
            'kategori': request.env['laporan.kategori'].search([('active', '=', True)]),
            'tag_ids': request.env['laporan.tag'].search([('active', '=', True)]),
            'jenis_akun_options': dict(request.env['res.partner']._fields['jenis_akun'].selection)
        }
        
        # Restore form values jika ada error
        if kw:
            values.update({
                'nama_akun': kw.get('nama_akun'),
                'link_fb': kw.get('link_fb'),
                'jenis_akun': kw.get('jenis_akun'),
                'deskripsi': kw.get('deskripsi'),
                'selected_tags': [int(x) for x in kw.get('tag_ids', '').split(',') if x]
            })
            
        return request.render("laporan_facebook.portal_create_laporan", values)

    @http.route(['/laporan/submit'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def laporan_submit(self, **post):
        """Handle submission laporan baru"""
        try:
            # Validasi input
            errors = {}
            
            if not post.get('nama_akun'):
                errors['nama_akun'] = 'Nama akun harus diisi'
                
            if not post.get('link_fb'):
                errors['link_fb'] = 'Link Facebook harus diisi'
                
            if not post.get('jenis_akun'):
                errors['jenis_akun'] = 'Jenis akun harus dipilih'
                
            if len(post.get('deskripsi', '').strip()) < 20:
                errors['deskripsi'] = 'Deskripsi minimal 20 karakter'
                
            files = request.httprequest.files.getlist('bukti')
            if not files or not any(f.filename for f in files):
                errors['bukti'] = 'Minimal harus melampirkan 1 bukti'
                
            if errors:
                raise ValidationError(json.dumps(errors))
            
            # Buat pelaku baru atau ambil existing
            Partner = request.env['res.partner'].sudo()
            domain = [
                ('link_fb', '=', post.get('link_fb')),
                ('is_pelaku', '=', True)
            ]
            pelaku = Partner.search(domain, limit=1)
            
            if not pelaku:
                pelaku_vals = {
                    'name': post.get('nama_akun'),
                    'link_fb': post.get('link_fb'),
                    'nama_akun': post.get('nama_akun'),
                    'jenis_akun': post.get('jenis_akun'),
                    'is_pelaku': True
                }
                pelaku = Partner.create(pelaku_vals)
            
            # Buat laporan
            Laporan = request.env['laporan.facebook'].sudo()
            vals = {
                'pelaku_id': pelaku.id,
                'deskripsi': post.get('deskripsi'),
                'created_user_id': request.env.user.id,
            }
            
            # Handle tags
            if post.get('tag_ids'):
                tag_ids = [int(x) for x in post.get('tag_ids').split(',') if x]
                if tag_ids:
                    vals['tag_ids'] = [(6, 0, tag_ids)]
            
            laporan = Laporan.create(vals)
            
            # Handle bukti
            Bukti = request.env['laporan.bukti'].sudo()
            for file in files:
                if file and file.filename:
                    # Validasi ukuran (max 10MB)
                    file_size = len(file.read())
                    if file_size > 10 * 1024 * 1024:
                        raise ValidationError(f"File {file.filename} melebihi batas 10MB")
                    
                    file.seek(0)  # Reset pointer setelah read
                    file_content = file.read()
                    
                    Bukti.create({
                        'laporan_id': laporan.id,
                        'nama_file': file.filename,
                        'tipe_file': self._get_file_type(file.filename),
                        'lampiran': base64.b64encode(file_content),
                        'created_user_id': request.env.user.id
                    })
            
            # Submit laporan
            laporan.action_submit()
            
            return request.redirect('/my/laporan')
            
        except ValidationError as e:
            # Handle validation errors
            try:
                errors = json.loads(str(e))
            except:
                errors = {'general': str(e)}
                
            values = {
                'error': errors,
                'kategori': request.env['laporan.kategori'].search([]),
                'tag_ids': request.env['laporan.tag'].search([]),
                'jenis_akun_options': dict(request.env['res.partner']._fields['jenis_akun'].selection),
                'post': post
            }
            return request.render("laporan_facebook.portal_create_laporan", values)
            
        except Exception as e:
            _logger.error("Error saat submit laporan: %s", str(e))
            return request.render("laporan_facebook.portal_create_laporan", {
                'error': {'general': 'Terjadi kesalahan sistem. Silakan coba lagi.'},
                'post': post
            })

    @http.route(['/laporan/search', '/laporan/search/page/<int:page>'], type='http', auth="public", website=True)
    def laporan_search(self, page=1, search='', sortby=None, filterby=None, **kw):
        """Public search page for laporan"""
        try:
            Laporan = request.env['laporan.facebook'].sudo()
            
            # Base domain
            domain = [
                ('status', '=', 'valid'),
                ('website_published', '=', True)
            ]
            
            # Search
            if search:
                domain += [
                    '|', '|', '|', '|',
                    ('kode_laporan', 'ilike', search),
                    ('nama_akun', 'ilike', search),
                    ('link_fb', 'ilike', search),
                    ('deskripsi', 'ilike', search),
                    ('tag_ids.nama', 'ilike', search)
                ]
            
            # Filter berdasarkan kategori
            if kw.get('kategori_id'):
                domain += [('tag_ids.kategori_id', '=', int(kw.get('kategori_id')))]
            
            # Filter berdasarkan tanggal
            if kw.get('date_from'):
                domain += [('tanggal_lapor', '>=', kw.get('date_from'))]
            if kw.get('date_to'):
                domain += [('tanggal_lapor', '<=', kw.get('date_to'))]
            
            # Sorting
            sort_options = {
                'date': {'label': 'Tanggal', 'order': 'tanggal_lapor desc'},
                'score': {'label': 'Skor', 'order': 'skor desc'},
                'reports': {'label': 'Jumlah Bukti', 'order': 'total_bukti desc'}
            }
            sort = sort_options.get(sortby, sort_options['date'])
            order = sort['order']
            
            # Count total
            total_count = Laporan.search_count(domain)
            
            # Paging
            url = '/laporan/search'
            if search:
                url += f'?search={search}'
                
            pager = portal_pager(
                url=url,
                url_args={
                    'sortby': sortby,
                    'filterby': filterby,
                    'kategori_id': kw.get('kategori_id'),
                    'date_from': kw.get('date_from'),
                    'date_to': kw.get('date_to')
                },
                total=total_count,
                page=page,
                step=20
            )
            
            # Get records
            laporan = Laporan.search(
                domain,
                order=order,
                limit=20,
                offset=pager['offset']
            )
            
            # Get kategori untuk filter
            kategori = request.env['laporan.kategori'].sudo().search([('active', '=', True)])
            
            values = {
                'laporan': laporan,
                'pager': pager,
                'search': search,
                'sortby': sortby,
                'sort_options': sort_options,
                'filterby': filterby,
                'kategori': kategori,
                'selected_kategori_id': int(kw.get('kategori_id', 0)),
                'date_from': kw.get('date_from'),
                'date_to': kw.get('date_to'),
                'total_count': total_count,
                'default_url': '/laporan/search'
            }
            
            return request.render("laporan_facebook.portal_search_laporan", values)
            
        except Exception as e:
            _logger.error("Error pada halaman search: %s", str(e))
            return request.not_found()

    @http.route(['/laporan/<int:laporan_id>'], type='http', auth="public", website=True)
    def laporan_detail(self, laporan_id, **kw):
        """Detail page for laporan"""
        try:
            # Get laporan dengan sudo untuk akses publik
            laporan = request.env['laporan.facebook'].sudo().browse(laporan_id)
            
            # Validasi akses dan status laporan
            if not laporan.exists() or not laporan.website_published or laporan.status != 'valid':
                return request.not_found()

            # Kelompokkan bukti berdasarkan tipe untuk tampilan
            bukti_by_type = {
                'image': laporan.bukti_ids.filtered(lambda b: b.tipe_file == 'image'),
                'document': laporan.bukti_ids.filtered(lambda b: b.tipe_file == 'document'),
                'video': laporan.bukti_ids.filtered(lambda b: b.tipe_file == 'video'),
                'link': laporan.bukti_ids.filtered(lambda b: b.tipe_file == 'link')
            }

            # Ambil laporan terkait (pelaku yang sama)
            related_laporan = request.env['laporan.facebook'].sudo().search([
                ('pelaku_id', '=', laporan.pelaku_id.id),
                ('id', '!=', laporan.id),
                ('status', '=', 'valid'),
                ('website_published', '=', True)
            ], limit=5)

            values = {
                'laporan': laporan,
                'bukti_by_type': bukti_by_type,
                'related_laporan': related_laporan,
                'page_name': 'laporan_detail'
            }

            # Track view jika belum dilihat di session ini
            if not request.session.get(f'viewed_laporan_{laporan.id}'):
                request.session[f'viewed_laporan_{laporan.id}'] = True
                laporan.sudo().write({
                    'view_count': laporan.view_count + 1
                })

            return request.render("laporan_facebook.portal_laporan_detail", values)
            
        except Exception as e:
            _logger.error("Error accessing laporan detail: %s", str(e))
            return request.not_found()

    @http.route(['/web/content/<string:model>/<int:id>/lampiran/<string:filename>'], type='http', auth='public')
    def bukti_content(self, model, id, filename, **kw):
        """Handle download file bukti"""
        try:
            # Validate model
            if model != 'laporan.bukti':
                return request.not_found()

            # Get bukti record
            bukti = request.env[model].sudo().browse(id)
            if not bukti.exists():
                return request.not_found()

            # Check laporan status & publication
            if not bukti.laporan_id.website_published or bukti.laporan_id.status != 'valid':
                return request.not_found()

            # Return file content
            return http.send_file(
                io.BytesIO(base64.b64decode(bukti.lampiran)),
                filename=filename,
                mimetype=bukti.file_mimetype
            )

        except Exception as e:
            _logger.error("Error serving bukti file: %s", str(e))
            return request.not_found()

    @http.route(['/laporan/preview/<int:bukti_id>'], type='http', auth='public', website=True)
    def bukti_preview(self, bukti_id, **kw):
        """Preview bukti in modal"""
        try:
            bukti = request.env['laporan.bukti'].sudo().browse(bukti_id)
            
            # Validate access
            if not bukti.exists() or not bukti.laporan_id.website_published:
                return request.not_found()

            values = {
                'bukti': bukti,
                'laporan': bukti.laporan_id
            }
            return request.render("laporan_facebook.modal_bukti_preview", values)

        except Exception as e:
            _logger.error("Error previewing bukti: %s", str(e))
            return request.not_found()

    @http.route(['/laporan/report'], type='json', auth='public', website=True)
    def report_laporan(self, laporan_id, reason=None, **kw):
        """Submit report/complaint for laporan"""
        try:
            if not reason:
                return {'error': 'Alasan harus diisi'}

            laporan = request.env['laporan.facebook'].sudo().browse(int(laporan_id))
            if not laporan.exists():
                return {'error': 'Laporan tidak ditemukan'}

            # Create report record
            request.env['laporan.report'].sudo().create({
                'laporan_id': laporan.id,
                'reason': reason,
                'reporter_ip': request.httprequest.remote_addr,
                'reporter_name': kw.get('name'),
                'reporter_email': kw.get('email')
            })

            # Notify admin
            admin_group = request.env.ref('laporan_facebook.group_admin', False)
            if admin_group and admin_group.users:
                laporan.sudo().message_post(
                    body=f"Laporan pengaduan baru dengan alasan: {reason}",
                    partner_ids=admin_group.users.mapped('partner_id').ids,
                    subject="Pengaduan Laporan",
                    message_type='notification',
                    subtype_xmlid='mail.mt_note'
                )

            return {'success': 'Laporan pengaduan telah dikirim'}

        except Exception as e:
            _logger.error("Error submitting report: %s", str(e))
            return {'error': 'Gagal mengirim laporan pengaduan'}