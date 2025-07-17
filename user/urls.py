from django.urls import path
from .views import (
    SendVerificationCodeView, RegisterView, LoginView, UserProfileView,
    TokenRefreshView, ChangePasswordView, RequestPasswordResetView,
    ResetPasswordWithCodeView, GenerateInvitationCodeView, UserInvitationView, UserRankingView,
    ClaimTemporaryInvitationView, MembershipPlansView, CreateMembershipOrderView,
    UserMembershipStatusView, UserMembershipOrdersView, SpendPointsView, SpendPointsForImageView,
    CheckPremiumAccessView, PointsConfigView, PointsTransactionHistoryView
)

urlpatterns = [
    # 使用与原来相同的 URL 路径
    path('send-code/', SendVerificationCodeView.as_view(), name='send_verification_code'),
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('profile/', UserProfileView.as_view(), name='user_profile'),
    path('refresh-token/', TokenRefreshView.as_view(), name='token_refresh'),

    # 邀请码相关
    path('generate-invitation-code/', GenerateInvitationCodeView.as_view(), name='generate_invitation_code'),
    path('invitation-info/', UserInvitationView.as_view(), name='user_invitation_info'),
    path('invitation-info/ranking/', UserRankingView.as_view(), name='user_ranking'),
    path('claim-temporary-invitation/', ClaimTemporaryInvitationView.as_view(), name='claim_temporary_invitation'),

    # 密码管理相关
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('request-password-reset/', RequestPasswordResetView.as_view(), name='request_password_reset'),
    path('reset-password-with-code/', ResetPasswordWithCodeView.as_view(), name='reset_password_with_code'),

    # 会员相关
    path('membership/plans/', MembershipPlansView.as_view(), name='membership_plans'),
    path('membership/orders/create/', CreateMembershipOrderView.as_view(), name='create_membership_order'),
    path('membership/status/', UserMembershipStatusView.as_view(), name='user_membership_status'),
    path('membership/orders/', UserMembershipOrdersView.as_view(), name='user_membership_orders'),

    # 积分相关
    path('points/spend/', SpendPointsView.as_view(), name='spend_points'),
    path('points/spend-for-image/', SpendPointsForImageView.as_view(), name='spend_points_for_image'),
    path('points/check-access/', CheckPremiumAccessView.as_view(), name='check_premium_access'),
    path('points/config/', PointsConfigView.as_view(), name='points_config'),
    path('points/transactions/', PointsTransactionHistoryView.as_view(), name='points_transaction_history'),
]
