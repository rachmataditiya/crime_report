from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
import random

_logger = logging.getLogger(__name__)

class LaporanTag(models.Model):
    _name = 'laporan.tag'
    _description = 'Tag Laporan'
    _order = 'kategori_id, sequence, nama'
    
    nama = fields.Char('Nama Tag', required=True, index=True)
    kategori_id = fields.Many2one('laporan.kategori', string='Kategori', 
                                 required=True, ondelete='restrict')
    warna = fields.Integer('Warna', default=lambda self: random.randint(1, 11))
    keterangan = fields.Text('Keterangan')
    bobot = fields.Float('Bobot Penilaian', default=1.0)
    sequence = fields.Integer('Urutan', default=10)
    active = fields.Boolean('Aktif', default=True)
    
    laporan_count = fields.Integer(
        string='Jumlah Laporan',
        compute='_compute_laporan_count',
        store=True
    )
    laporan_ids = fields.Many2many(
        'laporan.facebook',
        string='Laporan',
        relation='laporan_facebook_tag_rel',
        column1='tag_id',
        column2='laporan_id'
    )
    _sql_constraints = [
        ('nama_kategori_uniq', 
         'unique(nama, kategori_id)', 
         'Kombinasi nama tag dan kategori harus unik!')
    ]

    @api.depends('laporan_ids')
    def _compute_laporan_count(self):
        """Menghitung jumlah laporan yang menggunakan tag ini"""
        for tag in self:
            try:
                tag.laporan_count = self.env['laporan.facebook'].search_count([
                    ('tag_ids', 'in', tag.id)
                ])
            except Exception as e:
                _logger.error("Error menghitung jumlah laporan untuk tag %s: %s", 
                            tag.nama, str(e))
                tag.laporan_count = 0

    @api.constrains('bobot')
    def _check_bobot(self):
        """Validasi bobot penilaian"""
        for record in self:
            if record.bobot < 0:
                raise ValidationError("Bobot penilaian tidak boleh negatif")
            if record.bobot > 10:
                raise ValidationError("Bobot penilaian maksimal 10")

    @api.constrains('nama')
    def _check_nama(self):
        """Validasi format nama tag"""
        for record in self:
            if len(record.nama.strip()) < 2:
                raise ValidationError("Nama tag minimal 2 karakter")
            if not record.nama.replace(" ", "").isalnum():
                raise ValidationError("Nama tag hanya boleh mengandung huruf, angka dan spasi")

    @api.model
    def create(self, vals):
        """Override create untuk validasi tambahan"""
        try:
            # Cek status aktif kategori
            if vals.get('kategori_id'):
                kategori = self.env['laporan.kategori'].browse(vals['kategori_id'])
                if not kategori.active:
                    raise ValidationError(
                        "Tidak dapat membuat tag untuk kategori yang tidak aktif")
            
            # Normalisasi nama tag
            if vals.get('nama'):
                vals['nama'] = vals['nama'].strip()
            
            return super(LaporanTag, self).create(vals)
        except Exception as e:
            _logger.error("Error saat membuat tag: %s", str(e))
            raise

    def write(self, vals):
        """Override write untuk validasi perubahan"""
        try:
            # Cek perubahan kategori
            if vals.get('kategori_id'):
                kategori = self.env['laporan.kategori'].browse(vals['kategori_id'])
                if not kategori.active:
                    raise ValidationError(
                        "Tidak dapat memindahkan tag ke kategori yang tidak aktif")
                
            # Cek penggunaan tag sebelum dinonaktifkan
            if vals.get('active') is False:
                for record in self:
                    if record.laporan_count > 0:
                        raise UserError(
                            f"Tag '{record.nama}' masih digunakan dalam {record.laporan_count} laporan")
            
            return super(LaporanTag, self).write(vals)
        except Exception as e:
            _logger.error("Error saat update tag: %s", str(e))
            raise

    def unlink(self):
        """Override unlink untuk validasi penghapusan"""
        for record in self:
            try:
                if record.laporan_count > 0:
                    raise UserError(
                        f"Tidak dapat menghapus tag '{record.nama}' yang masih digunakan")
            except Exception as e:
                _logger.error("Error saat menghapus tag: %s", str(e))
                raise
        return super(LaporanTag, self).unlink()

    def action_view_laporan(self):
        """Action untuk melihat daftar laporan yang menggunakan tag ini"""
        self.ensure_one()
        try:
            return {
                'name': f'Laporan dengan tag {self.nama}',
                'type': 'ir.actions.act_window',
                'res_model': 'laporan.facebook',
                'view_mode': 'tree,form',
                'domain': [('tag_ids', 'in', self.id)],
                'context': {'default_tag_ids': [(6, 0, [self.id])]}
            }
        except Exception as e:
            _logger.error("Error saat membuka view laporan: %s", str(e))
            raise UserError("Tidak dapat membuka daftar laporan")