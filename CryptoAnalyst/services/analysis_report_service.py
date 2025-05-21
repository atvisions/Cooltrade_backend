from typing import Dict
from datetime import datetime, timezone
from CryptoAnalyst.models import Token, TechnicalAnalysis, AnalysisReport, Chain
from CryptoAnalyst.utils import logger

class AnalysisReportService:
    """分析报告服务类"""

    def save_analysis_report(self, symbol: str, analysis_data: Dict, language: str = 'zh-CN'):
        """保存分析报告

        Args:
            symbol: 代币符号
            analysis_data: 分析数据
            language: 语言代码，默认为'zh-CN'
        """
        try:
            # 统一 symbol 格式
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 查找代币
            token = Token.objects.get(symbol=clean_symbol)

            # 检查必要的键是否存在
            required_keys = [
                'trend_up_probability', 'trend_sideways_probability', 'trend_down_probability',
                'trend_summary', 'indicators_analysis', 'trading_action', 'trading_reason',
                'entry_price', 'stop_loss', 'take_profit', 'risk_level', 'risk_score', 'risk_details'
            ]
            for key in required_keys:
                if key not in analysis_data:
                    raise ValueError(f"缺少必要的键: {key}")

            # 获取或创建默认链
            chain, _ = Chain.objects.get_or_create(
                chain=clean_symbol,
                defaults={
                    'is_active': True,
                    'is_testnet': False
                }
            )

            # 获取最新的技术分析数据
            technical_analysis = TechnicalAnalysis.objects.filter(token=token).order_by('-timestamp').first()
            if not technical_analysis:
                raise ValueError(f"未找到代币 {clean_symbol} 的技术分析数据")

            # 获取当前价格（从技术分析数据中获取）
            current_price = technical_analysis.snapshot_price if hasattr(technical_analysis, 'snapshot_price') else 0
            # 如果技术分析数据中没有价格，尝试从最新的分析报告中获取
            if current_price == 0:
                latest_report = AnalysisReport.objects.filter(token=token).order_by('-timestamp').first()
                if latest_report:
                    current_price = latest_report.snapshot_price
                else:
                    # 如果没有任何价格数据，使用默认值
                    current_price = 0

            # 从 indicators_analysis 中提取各个指标的分析结果
            indicators = analysis_data['indicators_analysis']

            # 保存分析报告
            report = AnalysisReport.objects.create(
                token=token,
                timestamp=datetime.now(timezone.utc),
                technical_analysis=technical_analysis,
                snapshot_price=float(current_price),  # 添加报告生成时的价格
                language=language,  # 添加语言字段

                # 趋势分析
                trend_up_probability=int(analysis_data['trend_up_probability']),
                trend_sideways_probability=int(analysis_data['trend_sideways_probability']),
                trend_down_probability=int(analysis_data['trend_down_probability']),
                trend_summary=analysis_data['trend_summary'],

                # 指标分析
                # RSI
                rsi_analysis=indicators.get('RSI', {}).get('analysis', ''),
                rsi_support_trend=indicators.get('RSI', {}).get('support_trend', ''),

                # MACD
                macd_analysis=indicators.get('MACD', {}).get('analysis', ''),
                macd_support_trend=indicators.get('MACD', {}).get('support_trend', ''),

                # 布林带
                bollinger_analysis=indicators.get('BollingerBands', {}).get('analysis', ''),
                bollinger_support_trend=indicators.get('BollingerBands', {}).get('support_trend', ''),

                # BIAS
                bias_analysis=indicators.get('BIAS', {}).get('analysis', ''),
                bias_support_trend=indicators.get('BIAS', {}).get('support_trend', ''),

                # PSY
                psy_analysis=indicators.get('PSY', {}).get('analysis', ''),
                psy_support_trend=indicators.get('PSY', {}).get('support_trend', ''),

                # DMI
                dmi_analysis=indicators.get('DMI', {}).get('analysis', ''),
                dmi_support_trend=indicators.get('DMI', {}).get('support_trend', ''),

                # VWAP
                vwap_analysis=indicators.get('VWAP', {}).get('analysis', ''),
                vwap_support_trend=indicators.get('VWAP', {}).get('support_trend', ''),

                # 资金费率
                funding_rate_analysis=indicators.get('FundingRate', {}).get('analysis', ''),
                funding_rate_support_trend=indicators.get('FundingRate', {}).get('support_trend', ''),

                # 交易所净流入
                exchange_netflow_analysis=indicators.get('ExchangeNetflow', {}).get('analysis', ''),
                exchange_netflow_support_trend=indicators.get('ExchangeNetflow', {}).get('support_trend', ''),

                # NUPL
                nupl_analysis=indicators.get('NUPL', {}).get('analysis', ''),
                nupl_support_trend=indicators.get('NUPL', {}).get('support_trend', ''),

                # Mayer Multiple
                mayer_multiple_analysis=indicators.get('MayerMultiple', {}).get('analysis', ''),
                mayer_multiple_support_trend=indicators.get('MayerMultiple', {}).get('support_trend', ''),

                # 交易建议
                trading_action=analysis_data['trading_action'],
                trading_reason=analysis_data['trading_reason'],
                entry_price=float(analysis_data['entry_price']),
                stop_loss=float(analysis_data['stop_loss']),
                take_profit=float(analysis_data['take_profit']),

                # 风险评估
                risk_level=analysis_data['risk_level'],
                risk_score=int(analysis_data['risk_score']),
                risk_details=analysis_data['risk_details']
            )

            logger.info(f"成功保存{clean_symbol}的分析报告")
            return report

        except Exception as e:
            logger.error(f"保存{clean_symbol}的分析报告失败: {str(e)}")
            raise