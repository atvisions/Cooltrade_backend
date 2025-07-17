# Generated manually

from django.db import migrations

def create_initial_membership_plans(apps, schema_editor):
    """创建初始会员套餐"""
    MembershipPlan = apps.get_model('user', 'MembershipPlan')
    
    # 创建月付套餐
    MembershipPlan.objects.get_or_create(
        plan_type='monthly',
        defaults={
            'name': '高级会员月付',
            'price': 20.00,
            'duration_days': 30,
            'is_active': True
        }
    )
    
    # 创建年付套餐
    MembershipPlan.objects.get_or_create(
        plan_type='yearly',
        defaults={
            'name': '高级会员年付',
            'price': 188.00,
            'duration_days': 365,
            'is_active': True
        }
    )

def reverse_initial_membership_plans(apps, schema_editor):
    """删除初始会员套餐"""
    MembershipPlan = apps.get_model('user', 'MembershipPlan')
    MembershipPlan.objects.filter(plan_type__in=['monthly', 'yearly']).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('user', '0006_membershipplan_user_is_premium_and_more'),
    ]

    operations = [
        migrations.RunPython(
            create_initial_membership_plans,
            reverse_initial_membership_plans
        ),
    ]
