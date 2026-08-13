# -*- coding: utf-8 -*-
"""登录安全（暴力破解防护）测试。"""

from unittest.mock import patch

import pytest

from passportd.basis.errors import ApiError, ErrorCode
from passportd.libs.interface import LoginInterface
from passportd.utils.web import (
    check_account_locked,
    check_ip_rate_limit,
    clear_login_fail,
    record_login_fail,
)

# ---------- IP 限流 ----------

@patch("passportd.utils.web.rdb")
def test_check_ip_rate_limit_ok(mock_rdb):
    mock_rdb.incr.return_value = 5  # 窗口内 5 次，未超限（默认 20）
    check_ip_rate_limit("1.2.3.4")  # 不应抛错


@patch("passportd.utils.web.rdb")
def test_check_ip_rate_limit_first_call_sets_expire(mock_rdb):
    mock_rdb.incr.return_value = 1
    check_ip_rate_limit("1.2.3.4")
    mock_rdb.expire.assert_called_once()
    mock_rdb.expire.call_args.args[0].endswith("1.2.3.4")


@patch("passportd.utils.web.rdb")
def test_check_ip_rate_limit_blocked(mock_rdb):
    mock_rdb.incr.return_value = 21  # 超过默认 LOGIN_IP_LIMIT=20
    with pytest.raises(ApiError) as exc:
        check_ip_rate_limit("1.2.3.4")
    assert exc.value.code == ErrorCode.RATE_LIMITED


# ---------- 账号锁定 ----------

@patch("passportd.utils.web.rdb")
def test_check_account_locked_not_locked(mock_rdb):
    mock_rdb.exists.return_value = 0
    check_account_locked("test@example.com")  # 不应抛错


@patch("passportd.utils.web.rdb")
def test_check_account_locked_blocked(mock_rdb):
    mock_rdb.exists.return_value = 1
    mock_rdb.ttl.return_value = 600  # 剩余 10 分钟
    with pytest.raises(ApiError) as exc:
        check_account_locked("test@example.com")
    assert exc.value.code == ErrorCode.ACCOUNT_LOCKED


@patch("passportd.utils.web.rdb")
def test_record_login_fail_under_threshold(mock_rdb):
    mock_rdb.incr.return_value = 3  # 连续 3 次失败，未达阈值（默认 5）
    record_login_fail("test@example.com")
    mock_rdb.setex.assert_not_called()


@patch("passportd.utils.web.rdb")
def test_record_login_fail_reaches_threshold(mock_rdb):
    mock_rdb.incr.return_value = 5  # 达到默认阈值 LOGIN_FAIL_MAX=5
    record_login_fail("test@example.com")
    mock_rdb.setex.assert_called_once()
    mock_rdb.delete.assert_called_once()  # 锁定后清除失败计数


@patch("passportd.utils.web.rdb")
def test_clear_login_fail_deletes_both_keys(mock_rdb):
    clear_login_fail("test@example.com")
    assert mock_rdb.delete.call_count == 2


# ---------- LoginInterface 集成 ----------

@patch("passportd.libs.interface.clear_login_fail")
@patch("passportd.libs.interface.record_login_fail")
@patch("passportd.libs.interface.check_account_locked")
@patch("passportd.libs.interface.check_ip_rate_limit")
@patch("passportd.libs.interface.get_ip", return_value="1.2.3.4")
@patch("passportd.libs.interface.login")
def test_login_interface_success_clears_fail(
    mock_login, mock_get_ip, mock_ip, mock_locked, mock_record, mock_clear
):
    mock_login.return_value = True
    res = LoginInterface("test@example.com", "password123")
    assert res["success"] is True
    mock_clear.assert_called_once_with("test@example.com")
    mock_record.assert_not_called()


@patch("passportd.libs.interface.clear_login_fail")
@patch("passportd.libs.interface.record_login_fail")
@patch("passportd.libs.interface.check_account_locked")
@patch("passportd.libs.interface.check_ip_rate_limit")
@patch("passportd.libs.interface.get_ip", return_value="1.2.3.4")
@patch("passportd.libs.interface.login")
def test_login_interface_wrong_password_records_fail(
    mock_login, mock_get_ip, mock_ip, mock_locked, mock_record, mock_clear
):
    mock_login.return_value = False
    res = LoginInterface("test@example.com", "wrong-password")
    assert res["success"] is False
    assert res["message"] == "Verification failed"
    mock_record.assert_called_once_with("test@example.com")


@patch("passportd.libs.interface.record_login_fail")
@patch("passportd.libs.interface.check_ip_rate_limit")
@patch("passportd.libs.interface.check_account_locked")
@patch("passportd.libs.interface.get_ip", return_value="1.2.3.4")
@patch("passportd.libs.interface.login")
def test_login_interface_locked_returns_code(
    mock_login, mock_get_ip, mock_locked, mock_ip, mock_record
):
    mock_locked.side_effect = ApiError("locked", code=ErrorCode.ACCOUNT_LOCKED)
    res = LoginInterface("test@example.com", "password123")
    assert res["success"] is False
    assert res.get("code") == ErrorCode.ACCOUNT_LOCKED
    mock_login.assert_not_called()  # 锁定时不进行密码校验
    mock_record.assert_not_called()  # 锁定也不计入失败


@patch("passportd.libs.interface.check_ip_rate_limit", side_effect=ApiError(
    "too many login attempts, please try again later", code=ErrorCode.RATE_LIMITED
))
@patch("passportd.libs.interface.get_ip", return_value="1.2.3.4")
@patch("passportd.libs.interface.login")
def test_login_interface_ip_limited(mock_login, mock_get_ip, mock_ip):
    res = LoginInterface("test@example.com", "password123")
    assert res["success"] is False
    assert res.get("code") == ErrorCode.RATE_LIMITED
    mock_login.assert_not_called()


@patch("passportd.libs.interface.record_login_fail")
@patch("passportd.libs.interface.check_ip_rate_limit")
@patch("passportd.libs.interface.check_account_locked")
@patch("passportd.libs.interface.login")
def test_login_interface_empty_args_skipped(mock_login, mock_locked, mock_ip, mock_record):
    res = LoginInterface("", "")
    assert res["success"] is False
    assert res["message"] == "Invalid account or credential"
    mock_login.assert_not_called()  # 空账号/空密码不校验、不计数
    mock_record.assert_not_called()
    mock_locked.assert_not_called()
    mock_ip.assert_not_called()
