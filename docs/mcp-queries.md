# 메시지 조회

MCP는 본문과 함께 확인된 발신자·대화방 이름, 본인 메시지 여부, 원본 발신 시각, 별도의 서버 수집 시각을 제공합니다. 원격 MCP, stdio MCP, 인증된 HTTP `/v2` 경로에서 같은 방식으로 조회합니다.

| 도구 | 용도 |
| --- | --- |
| `get_recent_messages` | 발신 시각순 최신 메시지. 방·발신자·기간 필터 지원 |
| `search_messages` | 본문의 문자열 포함 검색과 같은 필터 |
| `list_conversations` | 방 목록, 이름, 보관 메시지 수, 최신 메시지 시각. `q`로 방 이름 필터 |
| `get_conversation_context` | 반환된 `message_id` 앞뒤의 같은 방 수집 메시지 |
| `get_collector_status` | 수집 상태, 범위, 이름 조회 상태 |

<a id="message-results-and-pagination"></a>

## 메시지 결과와 페이지 조회

결과에는 `message_id`, 대화·발신자 정보, `is_mine`, `sent_at`, `collected_at`, `body`, `message_type`, `source`, `truncated`가 포함됩니다. 사용자에게 설명할 메시지 시각은 `sent_at`이며 `collected_at`은 수집기가 저장한 시각입니다. 발신 시각을 모르면 null로 유지하며 최신 결과의 마지막에 정렬하고 시간 필터에는 포함하지 않습니다. 메시지 종류는 카카오톡 원본 코드이며 원본 미디어를 내려받지 않습니다.

같은 필터로 `next_cursor`를 `cursor`에 넣으면 다음 과거 페이지를 조회합니다. 서명된 커서는 메시지 스냅샷과 정렬 경계를 고정합니다. 필터 변경, DB 복구, 보관 기간 정리는 커서를 무효화합니다. `sender_name`이나 방 이름 `q` 필터는 표시 정보·닉네임 근거가 바뀌어도 만료되지만 동일한 메타데이터 갱신은 영향을 주지 않습니다. `invalid_query_or_expired_cursor`가 나오면 커서 없이 다시 시작하세요. 다른 조회는 메시지 스냅샷을 유지하면서 페이지 사이 이름이 갱신될 수 있습니다.

문맥 조회는 반환된 `message_id`, `before`(0–30), `after`(0–30)를 받으며 앞뒤 기본값은 각각 5입니다. 대상 포함 시간순 메시지와 추가 문맥 존재 여부를 반환합니다. 채팅을 열거나 읽음 상태를 바꾸지 않습니다.

<a id="names"></a>

## 이름 조회

이름은 불변 메시지 수집과 별도로 조회하므로 기존 행을 다시 넣거나 이벤트를 중복 발행하지 않고 이름을 채울 수 있습니다. 오픈채팅 닉네임은 링크·방과 사용자에 함께 묶어 다른 방 이름을 재사용하지 않습니다.

로컬 DB를 읽기 전용으로 조회합니다. 오픈채팅은 `KakaoTalk2.db`의 정확한 멤버·링크 행을, 현재 프로필 어댑터는 발신자 ID로 `crypto_user_database.user`를 읽습니다. 카카오톡 이전 버전에서는 선택적으로 `friends` 테이블을 사용합니다. 멤버를 조합한 방 이름은 포함된 멤버가 모두 확인되어야 합니다. 본인은 `나`(`name_source="self"`), 이름이 없는 나와의 채팅방은 `나와의 채팅`(`self_chat`)으로 표시합니다.

본인 ID는 보낸 메시지가 없어도 카카오톡 LocalUser DataStore에서 읽습니다. 암호화된 오픈채팅 닉네임이 있으면 그 ID로 복호화되는지 확인하고, ID가 없거나 확인에 실패하면 본인이 보낸 최신 메시지의 발신자 ID를 사용합니다. 둘 다 없으면 오픈채팅 닉네임처럼 본인 ID가 필요한 조회는 `self_identity_unavailable`로 남습니다. 사용한 근거는 `/v1/status.identity_metadata.self_identity_source`의 `local_account`, `sent_message`, `unavailable`로 확인합니다.

최신 일반 프로필의 표시 우선순위는 앱과 같이 비어 있지 않은 `friend_nickname`, `contact_name`, `nickname` 순서입니다. 비활성 프로필(`relation=9`)은 `nickname`을 씁니다. 연락처 이름은 관측한 발신자의 정확한 카카오톡 사용자 행에서만 읽고 출처를 `crypto_user.contact_name`으로 표시합니다. 휴대폰 주소록을 순회하거나 전화번호로 사람을 연결하지 않습니다. PlusChat은 채널 ID·대화 ID가 모두 맞아야 하며, 방 이름은 멤버 또는 로컬 발신자 목록에 ID가 포함된 유일한 채널 행이 있어야 합니다.

이름에는 `name_status`, `name_reason`, `name_source`, `updated_at`을 제공합니다. 미조회는 `pending`, 행 없음은 `not_found`, 스키마·DB·복호화 오류는 `unavailable`입니다. 암호문을 이름으로 노출하거나 없는 이름을 만들어 내지 않습니다.

오픈채팅(`OM`/`OD`)의 본인이 아닌 발신자에게 현재 프로필이 없으면 보관된 종류 0 시스템 메시지의 feed 2(`member`) 또는 feed 4(`members`)에서 닉네임을 찾습니다. 같은 기기·등록 세대·대화·정확한 정수 사용자 ID가 일치해야 하며 일반 본문은 이름 근거로 쓰지 않습니다. 최신 원본 이벤트 시각을 우선하고 동률은 수집 메시지 ID로 결정합니다. 늦게 가져온 과거 이벤트가 최신 근거를 덮지 않습니다. 잘린 이벤트, 시각 미상, 미지원·잘못된 구조, 모호한 이름은 무시합니다. 파싱은 16,384자, 멤버 100명, 이름당 512자로 제한합니다.

이 경우 `name_status="historical"`, `name_reason="historical_name_current_unverified"`, `name_source="open_chat_feed.leave"` 또는 `"open_chat_feed.join"`을 반환합니다. `name_observed_at`은 닉네임 근거 이벤트의 시각, `name_evidence_message_id`는 문맥 조회용 보관 이벤트 ID이며 현재 프로필에는 둘 다 null입니다. `updated_at`은 계속 현재 프로필 조회 시각을 뜻합니다. 과거 이름임을 표시하세요. 현재 이름이나 각 메시지 발신 당시 이름이 검증됐다는 뜻이 아닙니다.

확인된 현재 프로필이 항상 우선하며 과거 근거가 있어도 프로필 갱신을 계속합니다. 보관 기간이 지나면 원본 이벤트와 근거를 함께 지우고, 남은 이전 이벤트를 사용하거나 미확인 상태로 돌아갑니다. API는 시작 시 보관된 이벤트를 색인하고 새 행 수집 시 갱신하며 메시지 재발행·이벤트 ID 변경은 하지 않습니다. 상태 집계는 `historical`과 `resolved`를 구분합니다.

수집기는 10초마다 관측된 방·발신자 쌍을 최대 50개 처리하고 최근 미조회 메시지를 우선합니다. HTTP 요청행 제한을 피하도록 대상을 제한된 JSON POST 본문으로 보냅니다. 확인된 이름은 1시간, 미확인 이름은 1분 후 재조회할 수 있습니다. 메타데이터 실패가 본문 수집을 버리거나 멈추게 하지는 않습니다. `/v1/status.identity_metadata`는 이름 없이 집계만 제공합니다.

카카오톡 26.8.2는 기존 `friends` 대신 SQLCipher DB에 일반 프로필을 저장합니다. Iris는 기기 내부의 기존 설정에서 암호를 도출하고 설정을 생성·변경하거나 키를 API·MCP·로그·디스크로 내보내지 않습니다. SQLCipher 의존성은 SHA-256으로 고정합니다. 비파괴 손상 처리기를 사용하며 마이그레이션이나 쓰기 가능한 DB 도우미를 실행하지 않습니다. 키 없음·비호환 스키마·레코드 부재는 지원되는 과거 오픈채팅 근거가 없다면 명시적 미확인 상태가 됩니다. 호환성과 검증 한계는 [Iris](iris.md)를 참고하세요.

<a id="http-and-compatibility"></a>

## HTTP와 호환성

- `GET /v2/messages`: 최신·검색 필터. 본문 검색에는 `q` 추가.
- `GET /v2/conversations`: `q`, `limit`, `cursor`.
- `GET /v2/context`: `message_id`, `before`, `after`.

모두 API 읽기 토큰이 필요합니다. OAuth MCP는 `kakao.read` 범위를 사용하며 원격 도구는 구조화된 출력 스키마를 제공합니다.

최근·검색·대화 목록 도구는 불투명 `cursor`로 페이지를 넘깁니다. 원격 MCP는 이 도구에 숫자 `after`·`cursor_epoch`를 보내면 인수 오류로 거부하므로 그런 인수를 보내는 클라이언트는 도구 목록을 갱신하세요. HTTP `/v1/messages`와 이벤트 도구(`get_pending_messages`, `acknowledge_messages`)는 숫자 수집 커서와 `cursor_epoch`를 사용합니다. 미처리 이벤트 페이지는 `id`와 원본 발신자 ID를 담은 행 구조를 쓰며, 해당 `id`를 문맥 조회의 `message_id`로 넘기면 이름을 포함한 문맥을 얻습니다. 조회 커서를 `acknowledge_messages`에 넘기지 마세요. 자동 이벤트 구독은 없습니다.

<a id="updating-the-iris-component"></a>

## Iris 구성 요소 업데이트

Iris는 자동으로 업데이트됩니다. 실행 중인 Iris가 이미지의 빌드가 아니면 수집기가 프로세스를 멈추고, 기기의 APK를 이미지 안 APK와 SHA-256으로 비교해 다르면 검증한 업로드로 교체한 뒤 다시 시작합니다. `./bridge upgrade`·`./bridge update`의 이미지 변경과 되돌리기 모두 별도 명령이 필요하지 않으며 카카오톡 재설치, 재로그인, 승인 변경은 하지 않습니다. 0.1.0이 쓰던 기기 내부 파일은 업데이트가 실패해 이전 버전으로 되돌아갈 때 필요하므로 새 수집기가 10분 넘게 동작한 뒤 정리합니다. 이름 조회 상태는 `get_collector_status`로 확인하세요. 자세한 경계는 [Iris](iris.md#iris-build-and-runtime-boundaries)를 참고하세요.
