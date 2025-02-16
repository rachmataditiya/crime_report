{
    'name': 'Pelaporan Akun Facebook',
    'version': '1.0',
    'category': 'Website',
    'summary': 'Aplikasi untuk melaporkan dan memantau akun Facebook yang diduga melakukan kejahatan',
    'description': """
Modul ini menyediakan fitur untuk:
- Membuat laporan akun Facebook mencurigakan
- Melakukan validasi bukti oleh admin
- Portal pencarian publik
- Sistem tag dan kategori
- Dashboard monitoring
""",
    'author': 'Arkana Solusi Digital',
    'website': 'https://arkana.co.id',
    'depends': [
        'base',
        'mail',
        'portal', 
        'website',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/kategori_data.xml',
        'data/penilaian_data.xml',
        'data/ir_sequence_data.xml',
        'views/laporan_views.xml',
        'views/bukti_views.xml', 
        'views/kategori_views.xml',
        'views/tag_views.xml',
        'views/penilaian_views.xml',
        'views/website_menu.xml',
        'views/portal_templates.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}