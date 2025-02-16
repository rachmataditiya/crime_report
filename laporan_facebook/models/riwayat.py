from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
import json
from datetime import datetime

_logger = logging.getLogger(__name__)

class LaporanRiwayat(models.Model):
    _name = 'laporan.riwayat'
    _description = 'Riwayat Laporan'
    _order = 'waktu desc, id desc'
    _rec_name = 'kode_riwayat'
    
    kode_riwayat = fields.Char('Kode Riwayat', readonly=True, copy=False)
    laporan_id = fields.Many2one(
        'laporan.facebook', 
        string='Laporan',
        required=True,
        ondelete='cascade',
        index=True
    )
    waktu = fields.Datetime(
        'Waktu',
        default=fields.Datetime.now,
        required=True,
        readonly=True
    )
    aksi = fields.Selection([
        ('create', 'Pembuatan'),
        ('write', 'Perubahan'),
        ('unlink', 'Penghapusan'),
        ('validate', 'Validasi'),
        ('reject', 'Penolakan'),
        ('submit', 'Pengajuan'),
        ('cancel', 'Pembatalan'),
        ('need_info', 'Permintaan Info'),
    ], string='Jenis Perubahan', required=True)
    
    pengguna_id = fields.Many2one(
        'res.users',
        string='Pengguna',
        required=True,
        readonly=True,
        default=lambda self: self.env.user.id
    )
    nilai_lama = fields.Json('Data Sebelum', readonly=True)
    nilai_baru = fields.Json('Data Setelah', readonly=True)
    keterangan = fields.Text('Keterangan')
    
    # Fields komputasi untuk tampilan
    perubahan_ringkas = fields.Text(
        'Ringkasan Perubahan',
        compute='_compute_perubahan_ringkas'
    )
    status_laporan = fields.Selection(
        related='laporan_id.status',
        string='Status Laporan',
        store=True
    )
    bukti_id = fields.Many2one(
        'laporan.bukti',
        string='Bukti Terkait'
    )
    @api.model
    def create(self, vals):
        """Override create untuk generate kode riwayat"""
        try:
            if vals.get('kode_riwayat', 'New') == 'New':
                vals['kode_riwayat'] = self.env['ir.sequence'].next_by_code(
                    'laporan.riwayat'
                ) or 'New'
            return super(LaporanRiwayat, self).create(vals)
        except Exception as e:
            _logger.error("Error membuat riwayat: %s", str(e))
            raise

    @api.depends('nilai_lama', 'nilai_baru', 'aksi')
    def _compute_perubahan_ringkas(self):
        """Menghitung ringkasan perubahan yang terjadi"""
        for record in self:
            try:
                ringkasan = []
                
                if record.aksi in ['create', 'unlink']:
                    ringkasan.append(dict(record._fields['aksi'].selection).get(record.aksi))
                else:
                    # Bandingkan nilai lama dan baru
                    if record.nilai_lama and record.nilai_baru:
                        lama = json.loads(record.nilai_lama) if isinstance(record.nilai_lama, str) else record.nilai_lama
                        baru = json.loads(record.nilai_baru) if isinstance(record.nilai_baru, str) else record.nilai_baru
                        
                        for key in set(list(lama.keys()) + list(baru.keys())):
                            nilai_lama = lama.get(key)
                            nilai_baru = baru.get(key)
                            if nilai_lama != nilai_baru:
                                field_info = record.laporan_id._fields.get(key)
                                if field_info:
                                    field_label = field_info.string
                                    ringkasan.append(f"{field_label}: {nilai_lama} → {nilai_baru}")
                
                record.perubahan_ringkas = "\n".join(ringkasan) if ringkasan else "-"
            except Exception as e:
                _logger.error("Error menghitung ringkasan perubahan: %s", str(e))
                record.perubahan_ringkas = "Error: Gagal menghitung ringkasan"

    def _prepare_history_data(self, record, aksi, nilai_lama=None, nilai_baru=None, keterangan=None):
        """Menyiapkan data untuk pencatatan riwayat"""
        try:
            return {
                'laporan_id': record.id,
                'aksi': aksi,
                'pengguna_id': self.env.user.id,
                'nilai_lama': json.dumps(nilai_lama) if nilai_lama else None,
                'nilai_baru': json.dumps(nilai_baru) if nilai_baru else None,
                'keterangan': keterangan,
                'waktu': fields.Datetime.now()
            }
        except Exception as e:
            _logger.error("Error menyiapkan data riwayat: %s", str(e))
            raise

    def catat_perubahan(self, record, aksi, nilai_lama=None, nilai_baru=None, keterangan=None):
        """Method untuk mencatat perubahan"""
        try:
            vals = self._prepare_history_data(record, aksi, nilai_lama, nilai_baru, keterangan)
            return self.create(vals)
        except Exception as e:
            _logger.error("Error mencatat perubahan: %s", str(e))
            # Tidak raise error agar proses utama tetap berjalan
            return False

    def get_perubahan_detail(self):
        """Mendapatkan detail perubahan dalam format yang mudah dibaca"""
        self.ensure_one()
        try:
            result = {
                'kode_riwayat': self.kode_riwayat,
                'waktu': self.waktu,
                'pengguna': self.pengguna_id.name,
                'aksi': dict(self._fields['aksi'].selection).get(self.aksi),
                'perubahan': []
            }
            
            if self.nilai_lama and self.nilai_baru:
                lama = json.loads(self.nilai_lama) if isinstance(self.nilai_lama, str) else self.nilai_lama
                baru = json.loads(self.nilai_baru) if isinstance(self.nilai_baru, str) else self.nilai_baru
                
                for key in set(list(lama.keys()) + list(baru.keys())):
                    if lama.get(key) != baru.get(key):
                        field_info = self.laporan_id._fields.get(key)
                        if field_info:
                            result['perubahan'].append({
                                'field': field_info.string,
                                'nilai_lama': lama.get(key),
                                'nilai_baru': baru.get(key)
                            })
            
            return result
        except Exception as e:
            _logger.error("Error mendapatkan detail perubahan: %s", str(e))
            raise UserError("Gagal mendapatkan detail perubahan")

    def action_lihat_laporan(self):
        """Action untuk melihat laporan terkait"""
        self.ensure_one()
        try:
            return {
                'name': f'Laporan {self.laporan_id.kode_laporan}',
                'type': 'ir.actions.act_window',
                'res_model': 'laporan.facebook',
                'res_id': self.laporan_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        except Exception as e:
            _logger.error("Error membuka laporan: %s", str(e))
            raise UserError("Gagal membuka laporan")