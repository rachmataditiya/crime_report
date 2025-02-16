from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError 
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

class LaporanFacebook(models.Model):
    _name = 'laporan.facebook'
    _description = 'Laporan Akun Facebook'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    kode_laporan = fields.Char(
        'Nomor Laporan', 
        required=True,
        readonly=True,
        copy=False,
        default='/'
    )
    pelaku_id = fields.Many2one('res.partner', string='Pelaku', required=True, tracking=True)
    tanggal_lapor = fields.Datetime('Waktu Pelaporan', default=fields.Datetime.now, readonly=True)
    deskripsi = fields.Text('Uraian Kejadian', required=True, tracking=True)
    bukti_ids = fields.One2many('laporan.bukti', 'laporan_id', string='Bukti-bukti')
    tag_ids = fields.Many2many('laporan.tag', string='Tag')
    tag_kategori_ids = fields.Many2many(
        'laporan.kategori',
        string='Kategori dari Tag',
        compute='_compute_tag_kategori_ids',
        store=True)
    
    status = fields.Selection([
        ('draft', 'Draft'),
        ('menunggu', 'Menunggu Validasi'), 
        ('valid', 'Tervalidasi'),
        ('tolak', 'Ditolak'),
        ('info', 'Butuh Info Tambahan')
    ], string='Status', default='draft', tracking=True)
    
    skor = fields.Float('Skor', compute='_compute_skor', store=True)
    peninjau_id = fields.Many2one('res.users', string='Peninjau', readonly=True)
    
    # Fields untuk pelaku
    link_fb = fields.Char('Link Facebook', related='pelaku_id.link_fb', readonly=False)
    nama_akun = fields.Char('Nama Akun FB', related='pelaku_id.nama_akun', readonly=False)
    jenis_akun = fields.Selection(related='pelaku_id.jenis_akun', readonly=False)
    
    # Fields untuk statistics
    total_bukti = fields.Integer('Jumlah Bukti', compute='_compute_total_bukti', store=True)
    usia_laporan = fields.Integer('Usia Laporan (Hari)', compute='_compute_usia_laporan')
    
    # Fields untuk tracking
    created_user_id = fields.Many2one('res.users', string='Dibuat Oleh', default=lambda self: self.env.user, readonly=True)
    created_date = fields.Datetime('Tanggal Dibuat', default=fields.Datetime.now, readonly=True)
    validated_date = fields.Datetime('Tanggal Validasi', readonly=True)
    
    # Fields untuk portal
    website_published = fields.Boolean('Dipublikasi', default=False, copy=False)
    website_url = fields.Char('URL Website', compute='_compute_website_url')
    access_token = fields.Char('Access Token', copy=False)
    
    _sql_constraints = [
        ('kode_laporan_uniq', 'unique(kode_laporan)', 'Kode laporan harus unik!')
    ]

    @api.depends('bukti_ids')
    def _compute_total_bukti(self):
        for record in self:
            record.total_bukti = len(record.bukti_ids)

    @api.depends('tanggal_lapor')
    def _compute_usia_laporan(self):
        for record in self:
            if record.tanggal_lapor:
                usia = (datetime.now() - record.tanggal_lapor).days
                record.usia_laporan = max(0, usia)
            else:
                record.usia_laporan = 0

    def _compute_website_url(self):
        for record in self:
            record.website_url = f'/laporan/detail/{record.id}'

    @api.constrains('bukti_ids')
    def _check_bukti(self):
        for record in self:
            if len(record.bukti_ids) < 1:
                raise ValidationError("Minimal harus melampirkan 1 bukti untuk laporan")

    @api.constrains('deskripsi')
    def _check_deskripsi(self):
        for record in self:
            if len(record.deskripsi.strip()) < 20:
                raise ValidationError("Deskripsi harus minimal 20 karakter")

    @api.depends('bukti_ids', 'tag_ids', 'status')
    def _compute_skor(self):
        for record in self:
            try:
                skor = 0
                # Skor dari bukti
                bukti_skor = sum(bukti.calculate_score() for bukti in record.bukti_ids)
                
                # Skor dari tag
                tag_skor = sum(tag.bobot for tag in record.tag_ids)
                
                # Faktor pengali berdasarkan status validasi
                pengali = {
                    'draft': 0.8,
                    'menunggu': 1.0,
                    'valid': 1.5,
                    'tolak': 0.5,
                    'info': 0.9
                }.get(record.status, 1.0)
                
                # Hitung total skor
                record.skor = (bukti_skor + tag_skor) * pengali
                
                # Catat ke riwayat jika ada perubahan signifikan
                if abs(record.skor - record._origin.skor) > 10:
                    self.env['laporan.riwayat'].catat_perubahan(
                        record=record,
                        aksi='write',
                        nilai_lama={'skor': record._origin.skor},
                        nilai_baru={'skor': record.skor},
                        keterangan='Perubahan skor signifikan'
                    )
                    
            except Exception as e:
                _logger.error("Gagal menghitung skor untuk laporan %s: %s", record.kode_laporan, str(e))
                record.skor = 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            try:
                if vals.get('kode_laporan', 'New') == 'New':
                    vals['kode_laporan'] = self.env['ir.sequence'].next_by_code('laporan.facebook')
                    
                    
                # Set created info
                vals['created_user_id'] = self.env.user.id
                vals['created_date'] = fields.Datetime.now()
                
                # Generate access token
                vals['access_token'] = self._generate_access_token()
                
            except Exception as e:
                _logger.error("Error saat membuat laporan: %s", str(e))
                raise UserError(f"Gagal membuat laporan: {str(e)}")
                
        records = super().create(vals_list)
        
        # Catat riwayat pembuatan
        for record in records:
            self.env['laporan.riwayat'].catat_perubahan(
                record=record,
                aksi='create',
                nilai_baru=vals,
                keterangan='Pembuatan laporan baru'
            )
            
        return records

    def write(self, vals):
        # Simpan nilai lama untuk riwayat
        old_values = {
            field: getattr(self, field) 
            for field in vals.keys() 
            if field not in ['write_date', 'write_uid']
        }
        
        # Set tanggal validasi jika status berubah ke valid
        if vals.get('status') == 'valid':
            vals['validated_date'] = fields.Datetime.now()
            
        result = super().write(vals)
        
        # Catat riwayat perubahan
        self.env['laporan.riwayat'].catat_perubahan(
            record=self,
            aksi='write',
            nilai_lama=old_values,
            nilai_baru=vals
        )
        
        return result

    def unlink(self):
        for record in self:
            if record.status not in ['draft', 'tolak']:
                raise UserError("Hanya laporan draft atau ditolak yang dapat dihapus")
                
            # Catat riwayat penghapusan
            self.env['laporan.riwayat'].catat_perubahan(
                record=record,
                aksi='unlink',
                nilai_lama={'kode_laporan': record.kode_laporan}
            )
        
        return super().unlink()

    def action_submit(self):
        self.ensure_one()
        try:
            if self.status != 'draft':
                raise UserError("Hanya laporan draft yang dapat disubmit")
                
            if not self.bukti_ids:
                raise ValidationError("Tidak dapat submit laporan tanpa bukti")
                
            self.write({
                'status': 'menunggu',
                'tanggal_lapor': fields.Datetime.now()
            })
            
            # Kirim notifikasi ke peninjau
            peninjau_group = self.env.ref('laporan_facebook.group_peninjau')
            if peninjau_group:
                self.message_subscribe(partner_ids=peninjau_group.users.mapped('partner_id').ids)
                self.message_post(
                    body="Laporan baru memerlukan validasi",
                    message_type='notification',
                    subtype_xmlid='mail.mt_comment'
                )
                
            # Catat riwayat
            self.env['laporan.riwayat'].catat_perubahan(
                record=self,
                aksi='submit',
                keterangan='Pengajuan laporan untuk validasi'
            )
                
            return True
            
        except Exception as e:
            _logger.error("Gagal submit laporan %s: %s", self.kode_laporan, str(e))
            raise UserError(f"Gagal submit laporan: {str(e)}")

    def action_validate(self):
        self.ensure_one()
        try:
            if not self.env.user.has_group('laporan_facebook.group_peninjau'):
                raise UserError("Anda tidak memiliki hak untuk memvalidasi laporan")
            
            if self.status != 'menunggu':
                raise UserError("Hanya laporan dalam status menunggu yang dapat divalidasi")
            
            self.write({
                'status': 'valid',
                'peninjau_id': self.env.user.id,
                'validated_date': fields.Datetime.now()
            })
            
            # Catat riwayat
            self.env['laporan.riwayat'].catat_perubahan(
                record=self,
                aksi='validate',
                keterangan=f'Validasi oleh {self.env.user.name}'
            )
            
            # Notifikasi ke pelapor
            self.message_post(
                body="Laporan telah divalidasi",
                message_type='notification',
                subtype_xmlid='mail.mt_comment',
                partner_ids=[self.create_uid.partner_id.id]
            )
            
            return True
            
        except Exception as e:
            _logger.error("Gagal validasi laporan %s: %s", self.kode_laporan, str(e))
            raise UserError(f"Gagal validasi laporan: {str(e)}")

    def action_reject(self):
        self.ensure_one()
        try:
            if not self.env.user.has_group('laporan_facebook.group_peninjau'):
                raise UserError("Anda tidak memiliki hak untuk menolak laporan")
            
            self.write({
                'status': 'tolak',
                'peninjau_id': self.env.user.id
            })
            
            # Catat riwayat
            self.env['laporan.riwayat'].catat_perubahan(
                record=self,
                aksi='reject',
                keterangan=f'Penolakan oleh {self.env.user.name}'
            )
            
            # Notifikasi ke pelapor
            self.message_post(
                body="Laporan ditolak",
                message_type='notification',
                subtype_xmlid='mail.mt_comment',
                partner_ids=[self.create_uid.partner_id.id]
            )
            
            return True
            
        except Exception as e:
            _logger.error("Gagal menolak laporan %s: %s", self.kode_laporan, str(e))
            raise UserError(f"Gagal menolak laporan: {str(e)}")

    def action_need_info(self):
        self.ensure_one()
        try:
            if not self.env.user.has_group('laporan_facebook.group_peninjau'):
                raise UserError("Anda tidak memiliki hak untuk meminta informasi tambahan")
            
            self.write({'status': 'info'})
            
            # Catat riwayat
            self.env['laporan.riwayat'].catat_perubahan(
                record=self,
                aksi='need_info',
                keterangan=f'Permintaan informasi tambahan oleh {self.env.user.name}'
            )
            
            # Notifikasi ke pelapor
            self.message_post(
                body="Diperlukan informasi tambahan untuk laporan ini",
                message_type='notification',
                subtype_xmlid='mail.mt_comment',
                partner_ids=[self.create_uid.partner_id.id]
            )
            
            return True
            
        except Exception as e:
            _logger.error("Gagal meminta info laporan %s: %s", self.kode_laporan, str(e))
            raise UserError(f"Gagal meminta informasi tambahan: {str(e)}")

    def action_reset_draft(self):
        self.ensure_one()
        try:
            if self.status not in ['tolak', 'info']:
                raise UserError("Hanya laporan yang ditolak atau butuh info yang dapat dikembalikan ke draft")
            
            self.write({'status': 'draft'})
            
            # Catat riwayat
            self.env['laporan.riwayat'].catat_perubahan(
                record=self,
                aksi='write',
                nilai_lama={'status': self.status},
                nilai_baru={'status': 'draft'},
                keterangan='Reset ke draft'
            )
            
            return True
            
        except Exception as e:
            _logger.error("Gagal reset laporan %s: %s", self.kode_laporan, str(e))
            raise UserError(f"Gagal mengembalikan ke draft: {str(e)}")

    def _generate_access_token(self):
        """Generate unique access token untuk akses portal"""
        return self.env['ir.sequence'].next_by_code('laporan.access.token')

    def get_portal_url(self):
        """Get URL untuk akses portal dengan token"""
        self.ensure_one()
        return f'/laporan/detail/{self.id}?access_token={self.access_token}'

    def action_preview_portal(self):
        """Action untuk preview di portal"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.get_portal_url(),
            'target': 'new',
        }

    def get_report_data(self):
        """Mendapatkan data untuk report"""
        self.ensure_one()
        return {
            'kode_laporan': self.kode_laporan,
            'tanggal': self.tanggal_lapor,
            'status': dict(self._fields['status'].selection).get(self.status),
            'pelaku': {
                'nama': self.pelaku_id.name,
                'link_fb': self.link_fb,
                'nama_akun': self.nama_akun,
                'jenis_akun': dict(self.pelaku_id._fields['jenis_akun'].selection).get(self.jenis_akun),
            },
            'deskripsi': self.deskripsi,
            'bukti': [{
                'nama': bukti.nama_file,
                'tipe': dict(bukti._fields['tipe_file'].selection).get(bukti.tipe_file),
                'url': f'/web/content/{bukti._name}/{bukti.id}/lampiran'
            } for bukti in self.bukti_ids],
            'tag': self.tag_ids.mapped('nama'),
            'skor': self.skor,
            'pelapor': self.created_user_id.name,
            'peninjau': self.peninjau_id.name if self.peninjau_id else '-'
        }

    def action_get_riwayat(self):
        """Action untuk melihat riwayat laporan"""
        self.ensure_one()
        return {
            'name': f'Riwayat Laporan {self.kode_laporan}',
            'type': 'ir.actions.act_window',
            'res_model': 'laporan.riwayat',
            'view_mode': 'tree,form',
            'domain': [('laporan_id', '=', self.id)],
            'context': {'default_laporan_id': self.id},
            'target': 'current'
        }

    def notify_related_users(self, message, recipients=None):
        """Kirim notifikasi ke users terkait"""
        self.ensure_one()
        try:
            if recipients is None:
                recipients = []
                # Tambahkan pelapor
                if self.created_user_id.partner_id:
                    recipients.append(self.created_user_id.partner_id.id)
                # Tambahkan peninjau
                if self.peninjau_id.partner_id:
                    recipients.append(self.peninjau_id.partner_id.id)
                    
            if recipients:
                self.message_post(
                    body=message,
                    message_type='notification',
                    subtype_xmlid='mail.mt_comment',
                    partner_ids=recipients
                )
                
        except Exception as e:
            _logger.error("Gagal mengirim notifikasi untuk laporan %s: %s", 
                         self.kode_laporan, str(e))

    @api.model
    def _cron_check_pending_reports(self):
        """Cron job untuk cek laporan yang menunggu terlalu lama"""
        try:
            # Cari laporan yang menunggu > 7 hari
            domain = [
                ('status', '=', 'menunggu'),
                ('tanggal_lapor', '<', fields.Datetime.subtract(fields.Datetime.now(), days=7))
            ]
            pending_reports = self.search(domain)
            
            # Kirim notifikasi ke admin
            if pending_reports:
                admin_group = self.env.ref('laporan_facebook.group_admin')
                if admin_group and admin_group.users:
                    message = f"""
                    Terdapat {len(pending_reports)} laporan yang menunggu validasi > 7 hari:
                    {', '.join(pending_reports.mapped('kode_laporan'))}
                    """
                    for admin in admin_group.users:
                        pending_reports.message_post(
                            body=message,
                            message_type='notification',
                            subtype_xmlid='mail.mt_comment',
                            partner_ids=[admin.partner_id.id]
                        )
                        
        except Exception as e:
            _logger.error("Error pada cron check pending reports: %s", str(e))

    def export_report_xlsx(self):
        """Export laporan ke Excel"""
        self.ensure_one()
        try:
            data = self.get_report_data()
            # TODO: Implementasi export Excel menggunakan xlsxwriter
            return True
        except Exception as e:
            _logger.error("Gagal export Excel untuk laporan %s: %s", 
                         self.kode_laporan, str(e))
            raise UserError("Gagal mengexport laporan ke Excel")

    @api.model
    def get_statistics(self):
        """Mendapatkan statistik untuk dashboard"""
        try:
            stats = {
                'total': self.search_count([]),
                'draft': self.search_count([('status', '=', 'draft')]),
                'menunggu': self.search_count([('status', '=', 'menunggu')]),
                'valid': self.search_count([('status', '=', 'valid')]),
                'tolak': self.search_count([('status', '=', 'tolak')]),
                'info': self.search_count([('status', '=', 'info')]),
                'avg_score': self.search_read([('skor', '>', 0)], ['skor']),
                'top_tags': self.env['laporan.tag'].search_read(
                    domain=[],
                    fields=['nama', 'laporan_count'],
                    limit=5,
                    order='laporan_count desc'
                )
            }
            
            if stats['avg_score']:
                total_score = sum(record['skor'] for record in stats['avg_score'])
                stats['avg_score'] = total_score / len(stats['avg_score'])
            else:
                stats['avg_score'] = 0
                
            return stats
            
        except Exception as e:
            _logger.error("Gagal mendapatkan statistik: %s", str(e))
            return {}