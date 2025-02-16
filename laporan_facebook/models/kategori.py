from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)

class LaporanKategori(models.Model):
    _name = 'laporan.kategori'
    _description = 'Kategori Laporan'
    _parent_store = True
    _order = 'sequence, nama'
    
    nama = fields.Char('Nama Kategori', required=True, index=True)
    keterangan = fields.Text('Deskripsi')
    parent_id = fields.Many2one('laporan.kategori', 
                               string='Kategori Induk', 
                               ondelete='restrict', 
                               index=True)
    child_ids = fields.One2many('laporan.kategori', 
                               'parent_id', 
                               string='Sub Kategori')
    tag_ids = fields.One2many('laporan.tag', 
                             'kategori_id', 
                             string='Tag')
    parent_path = fields.Char(index=True)
    
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    level = fields.Integer(compute='_compute_level', store=True)

    total_laporan_count = fields.Integer(
        'Total Laporan',
        compute='_compute_total_laporan_count',
        store=True
    )
    complete_path = fields.Char(
        'Path Lengkap',
        compute='_compute_complete_path',
        store=True
    )

    _sql_constraints = [
        ('nama_uniq', 'unique (nama)', 'Nama kategori harus unik!')
    ]
    
    @api.depends('parent_id', 'parent_id.level')
    def _compute_level(self):
        """Menghitung level kedalaman kategori"""
        for record in self:
            if not record.parent_id:
                record.level = 0
            else:
                record.level = record.parent_id.level + 1

    @api.depends('tag_ids.laporan_ids')
    def _compute_total_laporan_count(self):
        """Menghitung total laporan dari semua tag"""
        for record in self:
            record.total_laporan_count = sum(tag.laporan_count for tag in record.tag_ids)

    @api.depends('nama', 'parent_id', 'parent_id.complete_path')
    def _compute_complete_path(self):
        """Menghitung path lengkap kategori"""
        for record in self:
            if record.parent_id:
                record.complete_path = f"{record.parent_id.complete_path} / {record.nama}"
            else:
                record.complete_path = record.nama

    @api.constrains('parent_id')
    def _check_hierarchy(self):
        """Mencegah recursive hierarchy"""
        if not self._check_recursion():
            raise ValidationError('Error! Tidak boleh membuat kategori secara rekursif.')

    def name_get(self):
        """Override name_get untuk menampilkan hierarki lengkap"""
        result = []
        for record in self:
            try:
                if record.parent_id:
                    name = f"{record.parent_id.name_get()[0][1]} / {record.nama}"
                else:
                    name = record.nama
                result.append((record.id, name))
            except Exception as e:
                _logger.error("Error saat generate nama kategori: %s", str(e))
                result.append((record.id, record.nama))
        return result

    def get_full_hierarchy(self):
        """Mendapatkan seluruh hierarki kategori"""
        self.ensure_one()
        try:
            hierarchy = []
            current = self
            while current:
                hierarchy.insert(0, current.nama)
                current = current.parent_id
            return ' / '.join(hierarchy)
        except Exception as e:
            _logger.error("Error saat get hierarki kategori: %s", str(e))
            return self.nama

    @api.model
    def create(self, vals):
        """Override create untuk validasi tambahan"""
        try:
            # Validasi nama kategori
            if vals.get('nama'):
                vals['nama'] = vals['nama'].strip()
                if len(vals['nama']) < 3:
                    raise ValidationError("Nama kategori minimal 3 karakter")
                
            # Cek duplikasi nama dalam satu level
            if vals.get('parent_id') and vals.get('nama'):
                same_level_categories = self.search([
                    ('parent_id', '=', vals['parent_id']),
                    ('nama', '=ilike', vals['nama'])
                ])
                if same_level_categories:
                    raise ValidationError(
                        f"Kategori dengan nama {vals['nama']} sudah ada pada level yang sama")
            
            return super().create(vals)
        except Exception as e:
            _logger.error("Error saat create kategori: %s", str(e))
            raise

    def write(self, vals):
        """Override write untuk validasi tambahan"""
        try:
            if 'nama' in vals:
                vals['nama'] = vals['nama'].strip()
                if len(vals['nama']) < 3:
                    raise ValidationError("Nama kategori minimal 3 karakter")

            for record in self:
                # Cek apakah kategori memiliki sub-kategori saat dinonaktifkan  
                if vals.get('active') is False:
                    if record.child_ids.filtered('active'):
                        raise UserError(
                            "Tidak dapat menonaktifkan kategori yang memiliki sub-kategori aktif")
                    if record.tag_ids.filtered('active'):
                        raise UserError(
                            "Tidak dapat menonaktifkan kategori yang memiliki tag aktif")
                
            return super().write(vals)
        except Exception as e:
            _logger.error("Error saat update kategori: %s", str(e))
            raise

    def unlink(self):
        """Override unlink untuk validasi penghapusan"""
        for record in self:
            try:
                if record.child_ids:
                    raise UserError(
                        "Tidak dapat menghapus kategori yang memiliki sub-kategori")
                if record.tag_ids:
                    raise UserError(
                        "Tidak dapat menghapus kategori yang memiliki tag")
            except Exception as e:
                _logger.error("Error saat hapus kategori: %s", str(e))
                raise
        return super().unlink()

    def toggle_active(self):
        """Toggle status aktif dengan validasi"""
        try:
            for record in self:
                if not record.active:
                    # Cek apakah parent aktif sebelum mengaktifkan
                    if record.parent_id and not record.parent_id.active:
                        raise UserError(
                            "Tidak dapat mengaktifkan kategori jika kategori induk tidak aktif")
                
            return super().toggle_active()
        except Exception as e:
            _logger.error("Error saat toggle active kategori: %s", str(e))
            raise