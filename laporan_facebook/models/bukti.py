from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError 
import base64
import magic
import hashlib
from PIL import Image, ImageDraw, ImageFont
import io
import os
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class LaporanBukti(models.Model):
    _name = 'laporan.bukti'
    _description = 'Bukti Laporan'
    _order = 'sequence, id'

    # Fields terkait laporan
    laporan_id = fields.Many2one('laporan.facebook', 
        string='Laporan',
        required=True,
        ondelete='cascade',
        index=True
    )
    sequence = fields.Integer('Urutan', default=10)
    
    # Fields untuk file
    nama_file = fields.Char('Nama File', required=True)
    tipe_file = fields.Selection([
        ('image', 'Gambar'),
        ('video', 'Video'),
        ('document', 'Dokumen'),
        ('link', 'Tautan')
    ], string='Tipe Dokumen', required=True)
    
    lampiran = fields.Binary('File Bukti', required=True, attachment=True)
    lampiran_filename = fields.Char('Nama File Lampiran')
    file_size = fields.Integer('Ukuran File', compute='_compute_file_size', store=True)
    file_mimetype = fields.Char('MIME Type', compute='_compute_file_mimetype', store=True)
    
    # Fields untuk watermark
    watermark = fields.Binary('Watermark')
    watermark_filename = fields.Char('Nama File Watermark')
    is_watermarked = fields.Boolean('Sudah Watermark', default=False)
    
    # Fields untuk metadata
    deskripsi = fields.Text('Deskripsi Bukti')
    tanggal_bukti = fields.Date('Tanggal Bukti')
    sumber = fields.Char('Sumber')
    checksum = fields.Char('Checksum', compute='_compute_checksum', store=True)
    
    # Fields untuk tracking
    created_user_id = fields.Many2one('res.users', 
        string='Dibuat Oleh',
        default=lambda self: self.env.user,
        readonly=True
    )
    created_date = fields.Datetime(
        'Tanggal Upload',
        default=fields.Datetime.now,
        readonly=True
    )

    # Computed fields
    status_laporan = fields.Selection(
        related='laporan_id.status',
        string='Status Laporan',
        store=True
    )
    preview_url = fields.Char('URL Preview', compute='_compute_preview_url')
    is_primary = fields.Boolean('Bukti Utama', default=False)
    version = fields.Integer('Versi', default=1)

    _sql_constraints = [
        ('checksum_uniq', 'unique(checksum)', 'File ini sudah pernah diupload sebelumnya!')
    ]

    @api.depends('lampiran')
    def _compute_file_size(self):
        """Menghitung ukuran file"""
        for record in self:
            try:
                if record.lampiran:
                    file_data = base64.b64decode(record.lampiran)
                    record.file_size = len(file_data)
                else:
                    record.file_size = 0
            except Exception as e:
                _logger.error("Gagal menghitung ukuran file: %s", str(e))
                record.file_size = 0

    @api.depends('lampiran', 'lampiran_filename')
    def _compute_file_mimetype(self):
        """Mendeteksi MIME type file"""
        for record in self:
            try:
                if record.lampiran:
                    file_data = base64.b64decode(record.lampiran)
                    mime = magic.Magic(mime=True)
                    record.file_mimetype = mime.from_buffer(file_data)
                else:
                    record.file_mimetype = False
            except Exception as e:
                _logger.error("Gagal mendeteksi MIME type: %s", str(e))
                record.file_mimetype = False

    @api.depends('lampiran')
    def _compute_checksum(self):
        """Menghitung checksum file untuk mencegah duplikasi"""
        for record in self:
            try:
                if record.lampiran:
                    file_data = base64.b64decode(record.lampiran)
                    record.checksum = hashlib.sha256(file_data).hexdigest()
                else:
                    record.checksum = False
            except Exception as e:
                _logger.error("Gagal menghitung checksum: %s", str(e))
                record.checksum = False

    def _compute_preview_url(self):
        """Generate URL untuk preview file"""
        for record in self:
            try:
                if record.tipe_file == 'link':
                    record.preview_url = record.deskripsi
                else:
                    record.preview_url = f'/web/content/{self._name}/{record.id}/lampiran'
            except Exception as e:
                _logger.error("Gagal generate preview URL: %s", str(e))
                record.preview_url = False

    @api.constrains('lampiran', 'tipe_file')
    def _check_file(self):
        """Validasi file yang diupload"""
        for record in self:
            try:
                if not record.lampiran:
                    continue

                file_data = base64.b64decode(record.lampiran)
                file_size = len(file_data)

                # Cek ukuran maksimum (10MB)
                if file_size > 10 * 1024 * 1024:
                    raise ValidationError("Ukuran file tidak boleh melebihi 10MB")

                # Cek tipe file
                mime = magic.Magic(mime=True)
                mimetype = mime.from_buffer(file_data)

                if record.tipe_file == 'image':
                    if not mimetype.startswith('image/'):
                        raise ValidationError("File harus berupa gambar")
                    # Validasi gambar
                    try:
                        img = Image.open(io.BytesIO(file_data))
                        img.verify()
                    except:
                        raise ValidationError("File bukan merupakan gambar yang valid")

                elif record.tipe_file == 'video':
                    if not mimetype.startswith('video/'):
                        raise ValidationError("File harus berupa video")

                elif record.tipe_file == 'document':
                    allowed_types = ['application/pdf', 'application/msword',
                                   'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
                    if mimetype not in allowed_types:
                        raise ValidationError("Format dokumen tidak didukung")

            except Exception as e:
                _logger.error("Gagal memvalidasi file: %s", str(e))
                raise ValidationError(f"Gagal memvalidasi file: {str(e)}")

    @api.model_create_multi
    def create(self, vals_list):
        """Override create untuk proses tambahan"""
        for vals in vals_list:
            try:
                # Set created info
                vals['created_user_id'] = self.env.user.id
                vals['created_date'] = fields.Datetime.now()

                # Generate nama file jika tidak ada
                if not vals.get('nama_file') and vals.get('lampiran_filename'):
                    vals['nama_file'] = vals['lampiran_filename']

                # Validasi tipe file link
                if vals.get('tipe_file') == 'link' and not vals.get('deskripsi'):
                    raise ValidationError("URL harus diisi untuk tipe bukti Link")

            except Exception as e:
                _logger.error("Error saat create bukti: %s", str(e))
                raise

        records = super().create(vals_list)

        # Proses watermark untuk gambar
        for record in records:
            if record.tipe_file == 'image':
                record._add_watermark()

        return records

    def write(self, vals):
        """Override write untuk proses tambahan"""
        if vals.get('lampiran'):
            # Reset watermark jika file berubah
            vals['is_watermarked'] = False
            vals['watermark'] = False

        result = super().write(vals)

        # Proses watermark jika file berubah
        if vals.get('lampiran'):
            for record in self:
                if record.tipe_file == 'image':
                    record._add_watermark()

        return result

    def _add_watermark(self):
        """Menambahkan watermark pada gambar"""
        self.ensure_one()
        try:
            if not self.lampiran or self.tipe_file != 'image' or self.is_watermarked:
                return

            # Decode gambar original
            image_data = base64.b64decode(self.lampiran)
            img = Image.open(io.BytesIO(image_data))

            # Konversi ke RGBA
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            # Buat layer untuk watermark
            txt = Image.new('RGBA', img.size, (255,255,255,0))
            draw = ImageDraw.Draw(txt)

            # Konfigurasi watermark
            watermark_text = f"""
            Laporan FB - {self.laporan_id.kode_laporan}
            {self.created_date.strftime('%Y-%m-%d %H:%M:%S')}
            """

            # Cari font
            font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'arial.ttf')
            if not os.path.exists(font_path):
                font_path = None
            font_size = int(min(img.size) / 20)
            font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

            # Hitung posisi watermark
            margin = 10
            text_width = max(draw.textlength(line, font=font) for line in watermark_text.split('\n'))
            text_height = font_size * len(watermark_text.split('\n'))
            x = img.size[0] - text_width - margin
            y = img.size[1] - text_height - margin

            # Gambar watermark dengan outline
            for adj in range(-2, 3):
                for adj2 in range(-2, 3):
                    draw.text((x+adj, y+adj2), watermark_text, font=font, fill=(0,0,0,128))
            draw.text((x, y), watermark_text, font=font, fill=(255,255,255,200))

            # Gabungkan gambar dengan watermark
            watermarked = Image.alpha_composite(img, txt)

            # Simpan hasil
            buffer = io.BytesIO()
            watermarked.save(buffer, format='PNG')
            self.watermark = base64.b64encode(buffer.getvalue())
            self.watermark_filename = f"watermark_{self.nama_file}"
            self.is_watermarked = True

        except Exception as e:
            _logger.error("Gagal menambahkan watermark: %s", str(e))
            raise ValidationError(f"Gagal menambahkan watermark: {str(e)}")

    def calculate_score(self):
        """Menghitung skor bukti"""
        self.ensure_one()
        try:
            base_score = 10
            
            # Faktor pengali berdasarkan tipe
            type_multiplier = {
                'image': 1.0,
                'video': 1.5,
                'document': 1.2,
                'link': 0.8
            }.get(self.tipe_file, 1.0)
            
            # Faktor pengali berdasarkan ukuran file
            size_multiplier = 1.0
            if self.file_size > 5 * 1024 * 1024:  # > 5MB
                size_multiplier = 1.2
            
            # Bonus untuk deskripsi lengkap
            description_bonus = 2 if self.deskripsi and len(self.deskripsi) > 50 else 0
            
            # Bonus untuk sumber yang jelas
            source_bonus = 3 if self.sumber else 0
            
            return (base_score * type_multiplier * size_multiplier) + description_bonus + source_bonus
            
        except Exception as e:
            _logger.error("Gagal menghitung skor bukti: %s", str(e))
            return 0

    def action_download(self):
        """Action untuk download file"""
        self.ensure_one()
        try:
            if self.tipe_file == 'link':
                raise UserError("Tidak dapat mendownload bukti bertipe Link")
                
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{self._name}/{self.id}/lampiran/{self.nama_file}',
                'target': 'self',
            }
        except Exception as e:
            _logger.error("Gagal mendownload file: %s", str(e))
            raise UserError(f"Gagal mendownload file: {str(e)}")

    def action_preview(self):
        """Action untuk preview file"""
        self.ensure_one()
        try:
            if self.tipe_file == 'link':
                return {
                    'type': 'ir.actions.act_url',
                    'url': self.deskripsi,
                    'target': 'new',
                }
            else:
                return {
                    'type': 'ir.actions.act_url',
                    'url': f'/web/content/{self._name}/{self.id}/lampiran',
                    'target': 'new',
                }
        except Exception as e:
            _logger.error("Gagal preview file: %s", str(e))
            raise UserError(f"Gagal membuka preview: {str(e)}")