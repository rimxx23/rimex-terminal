import pytest

from rimex.clients.geckoterminal import apply_holders
from rimex.clients.solana_rpc import apply_mint_account
from rimex.domain.models import TokenReport
from rimex.domain.risk import assess_honeypot
from rimex.presentation.api.schemas import ScanResponse
from rimex.presentation.telegram.cards import format_card
from tests.conftest import BONK

OWNER = "2apBGMsS6ti9RyF5TwQTDswXBWskiJP2LD4cUEDqYJjk"
HOOK_PROGRAM = "HookProgram1111111111111111111111111111111"


def token_2022_account(extensions: list[dict], freeze_authority: str | None = None) -> dict:
    return {
        "result": {
            "value": {
                "data": {
                    "program": "spl-token-2022",
                    "parsed": {
                        "type": "mint",
                        "info": {
                            "mintAuthority": None,
                            "freezeAuthority": freeze_authority,
                            "extensions": extensions,
                        },
                    },
                }
            }
        }
    }


def transfer_fee(bps: int, authority: str | None = None) -> dict:
    return {
        "extension": "transferFeeConfig",
        "state": {
            "olderTransferFee": {"transferFeeBasisPoints": 0},
            "newerTransferFee": {"transferFeeBasisPoints": bps},
            "transferFeeConfigAuthority": authority,
        },
    }


def scanned(extensions: list[dict], freeze_authority: str | None = None) -> TokenReport:
    report = TokenReport(address=BONK)
    apply_mint_account(report, token_2022_account(extensions, freeze_authority))
    return report


def test_parses_token_2022_extensions():
    report = scanned([
        transfer_fee(250, authority=OWNER),
        {"extension": "transferHook", "state": {"authority": OWNER, "programId": HOOK_PROGRAM}},
        {"extension": "permanentDelegate", "state": {"delegate": OWNER}},
    ])

    assert report.token_program == "spl-token-2022"
    assert report.transfer_fee_bps == 250
    assert report.transfer_fee_mutable is True
    assert report.transfer_hook_program == HOOK_PROGRAM
    assert report.permanent_delegate == OWNER


def test_transfer_fee_uses_highest_scheduled_value():
    report = scanned([{
        "extension": "transferFeeConfig",
        "state": {
            "olderTransferFee": {"transferFeeBasisPoints": 9900},
            "newerTransferFee": {"transferFeeBasisPoints": 100},
        },
    }])

    assert report.transfer_fee_bps == 9900


def test_empty_hook_and_delegate_are_not_flagged():
    report = scanned([
        {"extension": "transferHook", "state": {"authority": None, "programId": None}},
        {"extension": "permanentDelegate", "state": {"delegate": None}},
    ])

    assert assess_honeypot(report).level == "safe"


def test_classic_spl_token_without_extensions_is_safe():
    report = TokenReport(address=BONK, authorities_loaded=True)

    assessment = assess_honeypot(report)

    assert assessment.level == "safe"
    assert assessment.reasons == []


def test_unknown_when_rpc_data_missing():
    assert assess_honeypot(TokenReport(address=BONK)).level is None


@pytest.mark.parametrize(
    ("extensions", "freeze", "level", "reason"),
    [
        ([{"extension": "transferHook", "state": {"programId": HOOK_PROGRAM}}], None, "danger", "transfer hook can block selling"),
        ([{"extension": "permanentDelegate", "state": {"delegate": OWNER}}], None, "danger", "permanent delegate can move tokens from any wallet"),
        ([], OWNER, "danger", "freeze authority can freeze your tokens"),
        ([transfer_fee(1000)], None, "danger", "transfer fee 10%"),
        ([transfer_fee(999)], None, "warning", "transfer fee 9.99%"),
        ([transfer_fee(0, authority=OWNER)], None, "warning", "transfer fee can be raised"),
    ],
    ids=["hook", "delegate", "freeze", "fee-10pct", "fee-below-10pct", "fee-mutable"],
)
def test_honeypot_signals(extensions, freeze, level, reason):
    assessment = assess_honeypot(scanned(extensions, freeze))

    assert assessment.level == level
    assert reason in assessment.reasons


def test_danger_keeps_warning_reasons():
    report = scanned([
        {"extension": "permanentDelegate", "state": {"delegate": OWNER}},
        transfer_fee(0, authority=OWNER),
    ])

    assessment = assess_honeypot(report)

    assert assessment.level == "danger"
    assert assessment.reasons == [
        "permanent delegate can move tokens from any wallet",
        "transfer fee can be raised",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("yes", True), ("no", False), ("unknown", None), (None, None), ("YES", True)],
)
def test_geckoterminal_honeypot_flag(value, expected):
    report = TokenReport(address=BONK)

    apply_holders(report, {"data": {"attributes": {"is_honeypot": value}}})

    assert report.gt_honeypot is expected


def test_geckoterminal_flag_alone_is_danger():
    report = TokenReport(address=BONK, authorities_loaded=True, gt_honeypot=True)

    assert assess_honeypot(report).level == "danger"


def test_api_response_contains_honeypot_assessment():
    report = scanned([{"extension": "permanentDelegate", "state": {"delegate": OWNER}}])

    response = ScanResponse.from_report(report)

    assert response.honeypot_level == "danger"
    assert response.honeypot_reasons == ["permanent delegate can move tokens from any wallet"]
    assert response.permanent_delegate == OWNER


def test_bot_card_shows_honeypot_line_and_reasons():
    report = scanned([transfer_fee(1500)])

    card = format_card(report)

    assert "Honeypot: 🔴 sell restrictions" in card
    assert "  · transfer fee 15%" in card
