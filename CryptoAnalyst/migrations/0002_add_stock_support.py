# Generated manually for stock market support

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('CryptoAnalyst', '0001_initial'),
        ('user', '0005_remove_temporaryinvitation_session_key_and_more'),
    ]

    operations = [
        # Create MarketType model
        migrations.CreateModel(
            name='MarketType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(choices=[('crypto', 'Cryptocurrency'), ('stock', 'US Stock')], max_length=20, unique=True)),
                ('display_name', models.CharField(max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': '市场类型',
                'verbose_name_plural': '市场类型',
            },
        ),
        
        # Create Exchange model
        migrations.CreateModel(
            name='Exchange',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('display_name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('market_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exchanges', to='CryptoAnalyst.markettype')),
            ],
            options={
                'verbose_name': '交易所',
                'verbose_name_plural': '交易所',
            },
        ),
        
        # Create Asset model
        migrations.CreateModel(
            name='Asset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(max_length=20)),
                ('name', models.CharField(max_length=100)),
                ('address', models.CharField(blank=True, max_length=100)),
                ('decimals', models.IntegerField(blank=True, default=18, null=True)),
                ('sector', models.CharField(blank=True, max_length=100)),
                ('industry', models.CharField(blank=True, max_length=100)),
                ('market_cap', models.BigIntegerField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chain', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='assets', to='CryptoAnalyst.chain')),
                ('exchange', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='assets', to='CryptoAnalyst.exchange')),
                ('market_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assets', to='CryptoAnalyst.markettype')),
            ],
            options={
                'verbose_name': '资产',
                'verbose_name_plural': '资产',
            },
        ),
        
        # Add unique constraint for Asset
        migrations.AddConstraint(
            model_name='asset',
            constraint=models.UniqueConstraint(fields=('symbol', 'market_type'), name='unique_symbol_market_type'),
        ),
        
        # Add new fields to TechnicalAnalysis
        migrations.AddField(
            model_name='technicalanalysis',
            name='pe_ratio',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='technicalanalysis',
            name='pb_ratio',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='technicalanalysis',
            name='dividend_yield',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='technicalanalysis',
            name='week_52_high',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='technicalanalysis',
            name='week_52_low',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='technicalanalysis',
            name='avg_volume',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        
        # Make crypto-specific fields nullable
        migrations.AlterField(
            model_name='technicalanalysis',
            name='funding_rate',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='technicalanalysis',
            name='exchange_netflow',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='technicalanalysis',
            name='nupl',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='technicalanalysis',
            name='mayer_multiple',
            field=models.FloatField(blank=True, null=True),
        ),
        
        # Add asset field to TechnicalAnalysis
        migrations.AddField(
            model_name='technicalanalysis',
            name='asset',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='technical_analysis', to='CryptoAnalyst.asset'),
        ),
        
        # Add asset field to AnalysisReport
        migrations.AddField(
            model_name='analysisreport',
            name='asset',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='analysis_reports', to='CryptoAnalyst.asset'),
        ),
        
        # Create UserFavorite model
        migrations.CreateModel(
            name='UserFavorite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='favorited_by', to='CryptoAnalyst.asset')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='favorites', to='user.user')),
            ],
            options={
                'verbose_name': '用户收藏',
                'verbose_name_plural': '用户收藏',
            },
        ),
        
        # Add unique constraint for UserFavorite
        migrations.AddConstraint(
            model_name='userfavorite',
            constraint=models.UniqueConstraint(fields=('user', 'asset'), name='unique_user_asset_favorite'),
        ),
    ]
