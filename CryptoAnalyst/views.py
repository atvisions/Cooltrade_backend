from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .services.token_data_service import TokenDataService
from .services.gate_api import GateAPI
from .models import Token as CryptoToken, Chain, AnalysisReport, TechnicalAnalysis
from .utils import logger, sanitize_indicators, format_timestamp, parse_timestamp, safe_json_loads
import numpy as np
from typing import Dict, Optional, List
import pandas as pd
from datetime import datetime, timedelta
import pytz
from django.utils import timezone
import requests
import json
import time
import base64
import traceback
import os
from rest_framework.permissions import AllowAny
from django.shortcuts import render


class TokenDataAPIView(APIView):
    """代币数据API视图"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token_service = TokenDataService()  # 不传入API密钥，使用免费API

    def get(self, request, token_id: str):
        """获取指定代币的数据

        Args:
            request: HTTP请求对象
            token_id: 代币ID，例如 'bitcoin'

        Returns:
            Response: 包含代币数据的响应
        """
        try:
            # 获取代币数据
            token_data = self.token_service.get_token_data(token_id)

            return Response({
                'status': 'success',
                'data': token_data
            })

        except Exception as e:
            logger.error(f"获取代币数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _sanitize_float(self, value, min_val=-np.inf, max_val=np.inf):
        """将输入转换为有效的浮点数，并限制在指定范围内

        Args:
            value: 要处理的输入值
            min_val: 最小有效值，默认为负无穷
            max_val: 最大有效值，默认为正无穷

        Returns:
            float: 处理后的浮点数
        """
        try:
            result = float(value)
            if np.isnan(result) or np.isinf(result):
                return 0.0
            return max(min(result, max_val), min_val)
        except (ValueError, TypeError):
            return 0.0

# TokenRefreshView 已移至 user 应用
