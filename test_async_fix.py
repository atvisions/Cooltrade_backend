#!/usr/bin/env python3
"""
Test script to verify async database operations fix
"""
import os
import sys
import django
import asyncio
import requests
import json

# Add the backend directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from CryptoAnalyst.views_technical_indicators import TechnicalIndicatorsAPIView

async def test_async_database_operations():
    """Test async database operations"""
    print("Testing async database operations...")
    
    try:
        # Create a test user and token for authentication
        user, created = User.objects.get_or_create(
            username='testuser',
            defaults={'email': 'test@example.com'}
        )
        
        auth_token, created = Token.objects.get_or_create(user=user)
        print(f"Created test user with token: {auth_token.key}")
        
        # Create a request factory
        factory = RequestFactory()
        
        # Create a test request
        request = factory.get('/api/crypto/technical-indicators/BTCUSDT/', {
            'language': 'en-US'
        })
        
        # Add authentication
        request.META['HTTP_AUTHORIZATION'] = f'Token {auth_token.key}'
        request.user = user
        
        # Create view instance
        view = TechnicalIndicatorsAPIView()
        
        # Test the async method directly
        print("Testing async_get method...")
        response = await view.async_get(request, 'BTCUSDT')
        
        print(f"Response status: {response.status_code}")
        print(f"Response data: {response.data}")
        
        return True
        
    except Exception as e:
        print(f"Error during async test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_api_endpoint():
    """Test the actual API endpoint"""
    print("\nTesting API endpoint...")
    
    try:
        # Get or create test user token
        user, created = User.objects.get_or_create(
            username='testuser',
            defaults={'email': 'test@example.com'}
        )
        
        auth_token, created = Token.objects.get_or_create(user=user)
        
        # Make API request
        url = 'http://localhost:8000/api/crypto/technical-indicators/ETHUSDT/'
        headers = {
            'Authorization': f'Token {auth_token.key}',
            'Content-Type': 'application/json'
        }
        params = {
            'language': 'en-US'
        }
        
        print(f"Making request to: {url}")
        print(f"Headers: {headers}")
        print(f"Params: {params}")
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print("✅ API request successful!")
            data = response.json()
            print(f"Response data keys: {list(data.keys())}")
        else:
            print(f"❌ API request failed: {response.text}")
            
        return response.status_code == 200
        
    except requests.exceptions.ConnectionError:
        print("❌ Connection error - make sure Django server is running on localhost:8000")
        return False
    except Exception as e:
        print(f"❌ Error during API test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("🔧 Testing async database operations fix...")
    print("=" * 50)
    
    # Test 1: Async database operations
    async_result = asyncio.run(test_async_database_operations())
    
    # Test 2: API endpoint
    api_result = test_api_endpoint()
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"Async operations: {'✅ PASS' if async_result else '❌ FAIL'}")
    print(f"API endpoint: {'✅ PASS' if api_result else '❌ FAIL'}")
    
    if async_result and api_result:
        print("\n🎉 All tests passed! The async database fix is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Please check the error messages above.")
