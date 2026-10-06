"""Korean text for device error codes, shared by the admin screen and the device CLI."""

MESSAGES = {
    "adb_failed": "태블릿과 통신하지 못했습니다. redroid가 실행 중인지 확인하세요.",
    "root_adb_required": "태블릿의 관리자 ADB 연결을 사용할 수 없습니다. redroid를 다시 시작한 뒤 시도하세요.",
    "android_not_ready": "Android가 시작 중입니다. 잠시 기다린 뒤 설정을 새로고침하세요.",
    "device_state_unavailable": "태블릿 상태를 읽지 못했습니다. 잠시 후 다시 확인하세요.",
    "device_status_not_committed": "기기 상태를 수집 서버에 저장하지 못했습니다.",
    "kakao_signature_unverified": "카카오톡 배포자 서명을 확인할 수 없습니다. 공식 앱을 사용하고 설치 안내에서 지원하는 서명을 확인하세요.",
    "aurora_artifact_unverified": "다운로드한 Aurora가 지정된 릴리스와 일치하지 않습니다. 다시 시도하거나 APK 가져오기를 사용하세요.",
    "aurora_not_installed": "Aurora가 설치되어 있지 않습니다. ‘태블릿과 Aurora 준비’를 다시 실행하세요.",
    "screen_unavailable": "화면을 가져올 수 없습니다. redroid가 시작되었는지 확인하세요.",
    "keyboard_unavailable": "‘키보드 연결’을 누른 뒤 카카오톡 입력란을 선택하세요. 필요하면 먼저 ‘설치’에서 구성 요소를 설치하세요.",
    "keyboard_app_unavailable": "키보드 앱을 찾을 수 없습니다. ‘설치’에서 구성 요소를 다시 설치하세요.",
    "keyboard_app_unverified": "설치된 키보드 앱을 확인할 수 없습니다. ‘설치’에서 구성 요소를 다시 설치하세요.",
    "focus_kakao_input": "먼저 카카오톡의 입력란을 누르세요.",
    "input_result_unknown": "입력 결과를 확인할 수 없습니다. 다시 입력하기 전에 화면을 확인하세요.",
    "kakao_not_installed": "먼저 카카오톡 설치를 완료하세요.",
    "not_enrolled": "구성 요소가 아직 설치되지 않았습니다. ‘설치’를 먼저 진행하세요.",
    "not_tablet": "태블릿 설정이 아닙니다. 보조 기기 로그인을 위해 태블릿 설정이 필요합니다.",
    "display_too_small": "태블릿 화면 크기가 너무 작아 보조 기기 로그인을 사용할 수 없습니다.",
    "kakao_login_required": "태블릿 카카오톡에 아직 로그인되지 않았습니다. ‘다른 기기와 함께 사용’을 선택해 로그인하세요.",
    "account_ambiguous": "태블릿에 로그인된 카카오톡 계정을 확인할 수 없습니다. 카카오톡을 열어 로그인 상태를 확인하세요.",
    "account_changed": "승인한 계정과 다른 카카오톡 계정이 로그인되어 있습니다. 휴대폰을 확인하고 다시 승인하세요.",
    "android_changed": "Android가 바뀌어 수집이 멈췄습니다. 두 기기의 로그인을 확인하고 다시 승인하세요.",
    "approval_required": "휴대폰 로그인이 유지되는지 확인하고 메시지 수집을 시작하세요.",
    "phone_reported_lost": "휴대폰 로그아웃이 기록되어 수집이 멈췄습니다. 두 기기를 확인하고 다시 승인하세요.",
    "phone_confirmation_required": "휴대폰의 카카오톡 로그인이 유지되는지 직접 확인하세요.",
    "secondary_confirmation_required": "먼저 메시지 수집을 승인하세요.",
    "device_identity_changed": "DEVICE_ID가 등록 정보와 다릅니다. 이전 설정을 복구하세요.",
    "host_state_missing": "기기에는 등록 정보가 있지만 서버 상태가 없습니다. device-state를 먼저 복구하세요.",
    "enrollment_mismatch": "기기 등록 정보가 서버 상태와 다릅니다. 같은 시점의 백업을 복구하세요.",
}

GENERIC = "기기 작업에 실패했습니다. 연결과 설치 상태를 확인하세요."


def message(error, fallback=GENERIC):
    """Korean text for a known error code. Other errors may carry private input, so never echo them."""
    return MESSAGES.get(str(error), fallback)
