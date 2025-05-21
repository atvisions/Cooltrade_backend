from django.db import migrations

def create_initial_settings(apps, schema_editor):
    SystemSetting = apps.get_model('user', 'SystemSetting')
    
    # 创建邀请积分设置
    SystemSetting.objects.create(
        key='invitation_points',
        value='10',
        description='邀请新用户获得的积分数量'
    )

class Migration(migrations.Migration):

    dependencies = [
        ('user', '0002_systemsetting_alter_invitationcode_options_and_more'),
    ]

    operations = [
        migrations.RunPython(create_initial_settings),
    ]
