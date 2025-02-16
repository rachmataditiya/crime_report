from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    link_fb = fields.Char('Link Facebook')
    nama_akun = fields.Char('Nama Akun FB') 
    jenis_akun = fields.Selection([
        ('personal', 'Akun Personal'),
        ('bisnis', 'Akun Bisnis'),
        ('lainnya', 'Lainnya')
    ], string='Jenis Akun')
    is_pelaku = fields.Boolean(string="Pelaku", default=False)