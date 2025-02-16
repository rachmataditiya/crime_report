from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime
import ast
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

class LaporanPenilaian(models.Model):
    _name = 'laporan.penilaian'
    _description = 'Aturan Penilaian'
    _order = 'sequence'
    
    nama = fields.Char('Nama Aturan', required=True)
    tipe = fields.Selection([
        ('bukti', 'Jumlah Bukti'),
        ('tag', 'Tag'),
        ('waktu', 'Rentang Waktu'),
        ('kombinasi', 'Kombinasi'),
        ('custom', 'Custom Formula')
    ], string='Tipe Penilaian', required=True)
    
    bobot = fields.Float('Bobot', default=1.0)
    minimal = fields.Float('Skor Minimal', default=0)
    maksimal = fields.Float('Skor Maksimal')
    formula = fields.Text('Formula Perhitungan')
    sequence = fields.Integer('Urutan', default=10)
    active = fields.Boolean('Aktif', default=True)
    
    tag_ids = fields.Many2many('laporan.tag', string='Tag Terkait')
    keterangan = fields.Text('Keterangan')
    kategori_ids = fields.Many2many(
        'laporan.kategori',
        string='Kategori Terkait'
    )
    date_start = fields.Date('Tanggal Mulai Berlaku')
    date_end = fields.Date('Tanggal Akhir Berlaku')

    tag_ids = fields.Many2many('laporan.tag', 
        'penilaian_tag_rel', 
        'penilaian_id', 
        'tag_id', 
        string='Tag Terkait')

    kategori_ids = fields.Many2many('laporan.kategori',
        'penilaian_kategori_rel',
        'penilaian_id', 
        'kategori_id',
        string='Kategori Terkait')
    
    @api.constrains('formula')
    def _check_formula(self):
        """Validasi syntax formula"""
        for record in self:
            if record.tipe == 'custom' and record.formula:
                try:
                    # Coba parse formula untuk validasi syntax
                    ast.parse(record.formula)
                except Exception as e:
                    raise ValidationError(f"Formula tidak valid: {str(e)}")

    @api.constrains('bobot', 'minimal', 'maksimal')
    def _check_nilai(self):
        """Validasi nilai bobot dan batasan skor"""
        for record in self:
            if record.bobot <= 0:
                raise ValidationError("Bobot harus lebih besar dari 0")
            if record.maksimal and record.minimal >= record.maksimal:
                raise ValidationError("Skor minimal harus lebih kecil dari skor maksimal")

    def hitung_skor(self, laporan):
        """Menghitung skor berdasarkan aturan penilaian"""
        self.ensure_one()
        try:
            skor = 0
            
            if self.tipe == 'bukti':
                skor = self._hitung_skor_bukti(laporan)
            elif self.tipe == 'tag':
                skor = self._hitung_skor_tag(laporan)
            elif self.tipe == 'waktu':
                skor = self._hitung_skor_waktu(laporan)
            elif self.tipe == 'kombinasi':
                skor = self._hitung_skor_kombinasi(laporan)
            elif self.tipe == 'custom':
                skor = self._hitung_skor_custom(laporan)
            
            # Terapkan batas minimal dan maksimal
            if self.minimal is not None:
                skor = max(skor, self.minimal)
            if self.maksimal is not None:
                skor = min(skor, self.maksimal)
            
            return skor * self.bobot
            
        except Exception as e:
            _logger.error("Error menghitung skor untuk laporan %s: %s", 
                         laporan.kode_laporan, str(e))
            return 0

    def _hitung_skor_bukti(self, laporan):
        """Hitung skor berdasarkan bukti"""
        try:
            jumlah_bukti = len(laporan.bukti_ids)
            return jumlah_bukti * 10
        except Exception as e:
            _logger.error("Error hitung skor bukti: %s", str(e))
            return 0

    def _hitung_skor_tag(self, laporan):
        """Hitung skor berdasarkan tag"""
        try:
            skor = 0
            for tag in laporan.tag_ids:
                if tag in self.tag_ids:
                    skor += tag.bobot
            return skor
        except Exception as e:
            _logger.error("Error hitung skor tag: %s", str(e))
            return 0

    def _hitung_skor_waktu(self, laporan):
        """Hitung skor berdasarkan waktu"""
        try:
            if not laporan.tanggal_lapor:
                return 0
                
            usia_laporan = (datetime.now() - laporan.tanggal_lapor).days
            
            if usia_laporan <= 1:  # Laporan baru (< 24 jam)
                return 100
            elif usia_laporan <= 7:  # Laporan minggu ini
                return 75
            elif usia_laporan <= 30:  # Laporan bulan ini
                return 50
            else:
                return 25
        except Exception as e:
            _logger.error("Error hitung skor waktu: %s", str(e))
            return 0

    def _hitung_skor_kombinasi(self, laporan):
        """Hitung skor kombinasi dari berbagai faktor"""
        try:
            skor_bukti = self._hitung_skor_bukti(laporan)
            skor_tag = self._hitung_skor_tag(laporan)
            skor_waktu = self._hitung_skor_waktu(laporan)
            
            return (skor_bukti + skor_tag + skor_waktu) / 3
        except Exception as e:
            _logger.error("Error hitung skor kombinasi: %s", str(e))
            return 0

    def _hitung_skor_custom(self, laporan):
        """Hitung skor menggunakan formula kustom"""
        if not self.formula:
            return 0
            
        try:
            # Siapkan variabel yang bisa digunakan dalam formula
            env = {
                'laporan': laporan,
                'len': len,
                'sum': sum,
                'min': min,
                'max': max,
            }
            
            # Evaluasi formula dengan safe_eval
            skor = safe_eval.safe_eval(self.formula, env)
            return float(skor)
        except Exception as e:
            _logger.error("Error hitung skor custom: %s", str(e))
            return 0