# Data migration to initialize market types and exchanges

from django.db import migrations


def create_initial_data(apps, schema_editor):
    MarketType = apps.get_model('CryptoAnalyst', 'MarketType')
    Exchange = apps.get_model('CryptoAnalyst', 'Exchange')
    
    # Create market types
    crypto_market, _ = MarketType.objects.get_or_create(
        name='crypto',
        defaults={'display_name': 'Cryptocurrency'}
    )
    
    stock_market, _ = MarketType.objects.get_or_create(
        name='stock',
        defaults={'display_name': 'US Stock'}
    )
    
    # Create crypto exchanges
    Exchange.objects.get_or_create(
        name='binance',
        defaults={
            'display_name': 'Binance',
            'market_type': crypto_market
        }
    )
    
    Exchange.objects.get_or_create(
        name='gate',
        defaults={
            'display_name': 'Gate.io',
            'market_type': crypto_market
        }
    )
    
    # Create stock exchanges
    Exchange.objects.get_or_create(
        name='nasdaq',
        defaults={
            'display_name': 'NASDAQ',
            'market_type': stock_market
        }
    )
    
    Exchange.objects.get_or_create(
        name='nyse',
        defaults={
            'display_name': 'New York Stock Exchange',
            'market_type': stock_market
        }
    )


def migrate_existing_tokens(apps, schema_editor):
    """Migrate existing Token data to Asset model"""
    Token = apps.get_model('CryptoAnalyst', 'Token')
    Asset = apps.get_model('CryptoAnalyst', 'Asset')
    MarketType = apps.get_model('CryptoAnalyst', 'MarketType')
    TechnicalAnalysis = apps.get_model('CryptoAnalyst', 'TechnicalAnalysis')
    AnalysisReport = apps.get_model('CryptoAnalyst', 'AnalysisReport')
    
    crypto_market = MarketType.objects.get(name='crypto')
    
    # Migrate existing tokens to assets
    for token in Token.objects.all():
        asset, created = Asset.objects.get_or_create(
            symbol=token.symbol,
            market_type=crypto_market,
            defaults={
                'name': token.name,
                'chain': token.chain,
                'address': token.address,
                'decimals': token.decimals,
                'is_active': True
            }
        )
        
        # Update TechnicalAnalysis records
        TechnicalAnalysis.objects.filter(token=token).update(asset=asset)
        
        # Update AnalysisReport records
        AnalysisReport.objects.filter(token=token).update(asset=asset)


def reverse_migration(apps, schema_editor):
    """Reverse the migration if needed"""
    MarketType = apps.get_model('CryptoAnalyst', 'MarketType')
    Exchange = apps.get_model('CryptoAnalyst', 'Exchange')
    
    # Delete created data
    Exchange.objects.filter(market_type__name__in=['crypto', 'stock']).delete()
    MarketType.objects.filter(name__in=['crypto', 'stock']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('CryptoAnalyst', '0002_add_stock_support'),
    ]

    operations = [
        migrations.RunPython(create_initial_data, reverse_migration),
        migrations.RunPython(migrate_existing_tokens, migrations.RunPython.noop),
    ]
