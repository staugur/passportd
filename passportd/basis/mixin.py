# -*- coding: utf-8 -*-
"""
Copyright 2021 Hiroshi.tao

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formatdate
from json import dumps as json_dumps
from uuid import uuid4
from os.path import join
from os import makedirs
from base64 import b64decode
from hashlib import md5

import requests

from ..version import __version__
from .vars import PROC_NAME
from .conf import config
from .errors import ParamError, RunError
from .common import is_true
from ..utils.common import phone_check, multi_phone_check, logger


class GetItemMixIn(dict):
    """支持属性式访问的字典，访问不存在的 key 时抛出 AttributeError。

    使用示例::

        d = GetItemMixIn({"key": "value"})
        print(d.key)  # "value"
        print(d.nonexistent)  # raises AttributeError
    """

    def __getattr__(self, name):
        """通过属性语法访问字典键值。

        :param name: 键名
        :returns: 对应值
        :raises AttributeError: 键不存在时抛出
        """
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class GetItemEmptyMixIn(dict):
    """支持属性式访问的字典，访问不存在的 key 时返回空字符串。

    使用示例::

        d = GetItemEmptyMixIn({"key": "value"})
        print(d.nonexistent)  # ""
    """

    def __getattr__(self, name):
        """通过属性语法访问字典键值，不存在时返回空字符串。

        :param name: 键名
        :returns: 对应值或空字符串
        """
        try:
            return self[name]
        except KeyError:
            return ""


class RequestMixIn:
    """HTTP 请求 Mixin，提供带超时重试的 HTTP 请求能力。"""

    def http(
        self,
        url,
        params=None,
        data=None,
        json_data=None,
        headers=None,
        timeout=5,
        method="post",
        proxy=None,
        num_retries=1,
        _is_retry=False,
    ) -> requests.Response:
        """发起 HTTP 请求，支持超时自动重试。

        :param str url: 请求 URL
        :param dict params: 请求查询参数
        :param dict data: 提交表单数据
        :param dict json_data: 提交 JSON 数据
        :param dict headers: 请求头
        :param int timeout: 超时时间，单位秒
        :param str method: 请求方法（get / post / put / delete）
        :param str proxy: 代理服务器地址，仅重试时生效
        :param int num_retries: 超时重试次数
        :param bool _is_retry: 内部参数，标记是否为重试请求
        :returns: 请求响应对象
        :rtype: requests.Response
        :raises RunError: 请求失败且重试耗尽时抛出
        """
        headers = headers or {}
        headers["User-Agent"] = f"{PROC_NAME}/{__version__}"

        method = method.lower()
        if method == "get":
            method_func = requests.get
        elif method == "post":
            method_func = requests.post
        elif method == "put":
            method_func = requests.put
        elif method == "delete":
            method_func = requests.delete
        else:
            method_func = requests.post
        try:
            resp = method_func(
                url,
                params=params,
                headers=headers,
                data=data,
                json=json_data,
                timeout=timeout,
                proxies=proxy if _is_retry is True and proxy else None,
            )
            resp.raise_for_status()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if num_retries > 0:
                return self.http(
                    url,
                    params=params,
                    data=data,
                    json_data=json_data,
                    headers=headers,
                    timeout=timeout,
                    method=method,
                    proxy=proxy,
                    num_retries=num_retries - 1,
                    _is_retry=True,
                )
            else:
                raise RunError(e)
        except (requests.exceptions.RequestException, Exception) as e:
            raise RunError(e)
        else:
            return resp


class SMTPMixIn:
    """SMTP 邮件发送 Mixin，支持通过 SSL SMTP 发送 HTML 邮件。

    需在配置中设置 ``SMTP_USER_MAIL``、``SMTP_USER_PASSWD``、``SMTP_SERVER``、``SMTP_PORT``。
    """

    _smtp_user_mail: str = config.get("SMTP_USER_MAIL", "")
    _smtp_user_passwd: str = config.get("SMTP_USER_PASSWD", "")
    _smtp_server: str = config.get("SMTP_SERVER", "")
    _smtp_port: int = config.get("SMTP_PORT", 587)

    def smtp_send_email(
        self,
        to_addr: str,
        subject: str,
        body: str,
    ) -> bool:
        """发送HTML邮件消息

        :param str to_addr: 收件人地址，多个收件人用逗号分隔（英文）
        :param str subject: 主题
        :param str body: 邮件正文
        :returns: 发送成功返回 True
        :raises ParamError: 参数错误
        :raises RunError: 运行错误
        """
        if not to_addr or not subject or not body:
            raise ParamError("Invalid params")

        message = MIMEText(body, "html", "utf-8")
        message["From"] = self._smtp_user_mail
        message["To"] = to_addr
        message["Subject"] = Header(subject, "utf-8")  # type: ignore
        message["Date"] = formatdate(localtime=True)

        try:
            if self._smtp_port == 465:
                # 端口 465：隐式 SSL（SMTP_SSL）
                server = smtplib.SMTP_SSL(self._smtp_server, self._smtp_port)
            elif self._smtp_port == 25:
                raise RunError("SMTP port 25 is not allowed for security reasons")
            else:
                # 端口 587 等：明文连接 + STARTTLS 升级
                server = smtplib.SMTP(self._smtp_server, self._smtp_port)
                server.starttls()
            if config.get("DEBUG") is True:
                server.set_debuglevel(1)
            server.login(self._smtp_user_mail, self._smtp_user_passwd)
            server.sendmail(self._smtp_user_mail, to_addr, message.as_string())
            server.quit()
        except Exception as e:
            raise RunError(e)
        else:
            return True


class SpugMixIn(RequestMixIn):
    """Spug 邮件/短信发送 Mixin，通过 Spug Push API 发送通知。"""

    #: EMAIL
    _spug_mail_template_id: str = config.get("SPUG_MAIL_TEMPLATE_ID", "")

    #: SMS
    _spug_sms_template_id: str = config.get("SPUG_SMS_TEMPLATE_ID", "")

    def spug_send_email(
        self,
        to_addr: str,
        code: str,
    ) -> bool:
        """通过 Spug Push 发送邮件验证码。

        模板变量：${scene}、${code}、${minute}，scene 固定为"登录&注册"，minute 固定为 5。

        :param str to_addr: 收件人地址
        :param str code: 验证码
        :returns: 发送成功返回 True
        :raises ParamError: 参数错误
        :raises RunError: 发送失败
        """
        if not self._spug_mail_template_id:
            raise ParamError("SPUG_MAIL_TEMPLATE_ID is not configured")
        if not to_addr or not code:
            raise ParamError("Invalid params")

        apiurl = f"https://push.spug.cc/mail/{self._spug_mail_template_id}"
        data = {
            "to": to_addr,
            "code": code,
            "scene": "Passportd 登录&注册",
            "minute": "5",
        }
        res = self.http(apiurl, json_data=data, timeout=10).json()
        if res.get("code") == 200:
            return True
        else:
            e = "{code}: {msg}".format(code=res.get("code"), msg=res.get("msg"))
            raise RunError(e)

    def spug_send_sms(
        self,
        phone: str,
        code: str,
    ) -> bool:
        """通过 Spug Push 发送短信验证码。

        模板变量：${code}、${minute}，minute 固定为 5。

        :param str phone: 手机号码
        :param str code: 验证码
        :returns: 发送成功返回 True
        :raises ParamError: 参数错误
        :raises RunError: 发送失败
        """
        if not self._spug_sms_template_id:
            raise ParamError("SPUG_SMS_TEMPLATE_ID is not configured")
        if not multi_phone_check(phone) or not code:
            raise ParamError("Invalid phone or code")

        apiurl = f"https://push.spug.cc/sms/{self._spug_sms_template_id}"
        data = {
            "to": phone,
            "code": code,
            "minute": "5",
        }
        res = self.http(apiurl, json_data=data, timeout=10).json()
        if res.get("code") == 200:
            return True
        else:
            e = "{code}: {msg}".format(code=res.get("code"), msg=res.get("msg"))
            raise RunError(e)


class SendCloudMixIn(RequestMixIn):
    """SendCloud 邮件/短信发送 Mixin，继承自 RequestMixIn。"""

    #: EMAIL
    _sendcloud_api_user: str = config.get("SENDCLOUD_API_USER", "")
    _sendcloud_api_key: str = config.get("SENDCLOUD_API_KEY", "")
    _sendcloud_mail_from: str = config.get("SENDCLOUD_MAIL_FROM", "")

    #: SMS
    _sendcloud_sms_user: str = config.get("SENDCLOUD_SMS_USER", "")
    _sendcloud_sms_key: str = config.get("SENDCLOUD_SMS_KEY", "")
    _sendcloud_sms_template_id: str = config.get("SENDCLOUD_SMS_TEMPLATE_ID", "")

    def sendcloud_send_email(
        self,
        to_addr: str,
        subject: str,
        body: str,
    ) -> bool:
        """发送HTML邮件消息

        :param str to_addr: 收件人地址，多个收件人用分号分隔（英文）
        :param str subject: 主题
        :param str body: 邮件正文
        :returns: 发送成功返回 True
        :raises ParamError: 参数错误
        :raises RunError: 运行错误
        """
        if (
            not self._sendcloud_api_user
            or not self._sendcloud_api_key
            or not self._sendcloud_mail_from
        ):
            raise ParamError("Invalid email params")
        if not to_addr or not subject or not body:
            raise ParamError("Invalid params")

        apiurl = "https://api.sendcloud.net/apiv2/mail/send"
        data = {
            "apiUser": self._sendcloud_api_user,
            "apiKey": self._sendcloud_api_key,
            "from": self._sendcloud_mail_from,
            "to": to_addr.replace(",", ";"),
            "subject": subject,
            "html": body,
        }

        res = self.http(apiurl, data=data).json()
        if is_true(res.get("result")):
            return res.get("info")
        else:
            e = "{code}: {msg}".format(
                code=res.get("statusCode"), msg=res.get("message")
            )
            raise RunError(e)

    def sendcloud_send_sms(
        self,
        phone: str,
        code: str,
    ) -> bool:
        """发送HTML邮件消息

        :param str pone: 收件人地址，多个收件人用分号分隔（英文）
        :param str code: yanzhengma
        :returns: 发送成功返回 True
        :raises ParamError: 参数错误
        :raises RunError: 运行错误
        """
        apiurl = "https://api.sendcloud.net/smsapi/send"
        SMS_USER = self._sendcloud_sms_user
        SMS_KEY = self._sendcloud_sms_key
        SMS_TID = self._sendcloud_sms_template_id
        if not SMS_USER or not SMS_KEY or not SMS_TID:
            raise ParamError("Invalid sms params")
        if not phone_check(phone) or not code:
            raise ParamError("Invalid phone or code")

        param = {
            "smsUser": SMS_USER,
            "templateId": SMS_TID,
            "msgType": 0,
            "phone": phone,
            "vars": json_dumps(dict(code=code)),
        }

        param_keys = list(param.keys())
        param_keys.sort()

        param_str = ""
        for key in param_keys:
            param_str += f"{key}={param[key]}&"
        param_str = param_str[:-1]

        sign_str = f"{SMS_KEY}&{param_str}&{SMS_KEY}"
        param["signature"] = md5(sign_str.encode("utf-8")).hexdigest()

        res = self.http(apiurl, data=param).json()
        if is_true(res.get("result")):
            return res.get("info")
        else:
            e = "{code}: {msg}".format(
                code=res.get("statusCode"), msg=res.get("message")
            )
            raise RunError(e)


class SapicUploadMixIn(RequestMixIn):
    """Sapic 图床上传 Mixin，通过 API 上传 base64 图片并返回 URL。"""

    _sapic_apiurl: str = config.get("SAPIC_APIURL", "")
    _sapic_linktoken: str = config.get("SAPIC_LINKTOKEN", "")

    def sapic_base64_upload(self, content: str, *, title: str = "") -> str:
        """使用Sapic上传图片

        :param str content: 符合 Data URI 格式的图片 base64 编码内容
        :param str title: Sapic上传图片参数，指定图片标题
        :returns: uploaded image url
        :raises ParamError: 参数错误
        :raises RunError: 上传错误
        """
        if not self._sapic_linktoken or not self._sapic_apiurl:
            raise ParamError("Invalid sapic_linktoken or sapic_apiurl")

        apiurl: str = self._sapic_apiurl
        if apiurl and not apiurl.endswith("/api/upload"):
            apiurl = f"{apiurl.rstrip('/')}/api/upload"
        data = {"picbed": content, "title": title}
        headers = {
            "Authorization": f"LinkToken {self._sapic_linktoken}",
        }
        res = self.http(apiurl, data=data, headers=headers, timeout=30).json()
        if isinstance(res, dict) and "code" in res and "src" in res:
            if res["code"] == 0:
                return res["src"]
            else:
                raise RunError(res.get("msg"))
        else:
            raise RunError("Invalid sapic response")


class LocalUploadMixIn:
    """本地上传 Mixin，将 base64 图片保存到本地文件系统。

    上传目录由 ``LOCAL_UPLOAD_FOLDER`` 配置指定。
    """

    def local_base64_upload(self, content: str) -> str:
        """将 base64 编码的图片保存到本地。

        :param str content: 符合 Data URI 格式的图片 base64 编码内容（仅支持 jpeg/png）
        :returns: 保存的文件名称，需自行拼接路径或使用 ``url_for`` 构建路由
        :rtype: str
        :raises ParamError: MIME 类型不支持时抛出
        :raises RunError: base64 解码失败时抛出
        """

        # 提取MIME类型并校验
        header = content.split(",")[0] if "," in content else ""
        mime_type = header.split(";")[0].replace("data:", "")
        if mime_type not in ["image/jpeg", "image/png"]:
            raise ParamError("Invalid base64 format")
        try:
            data = b64decode(content.split(",")[1])
        except Exception:
            raise RunError("Invalid base64 content")

        # 生成唯一文件名
        upload_folder = config["LOCAL_UPLOAD_FOLDER"]
        ext = "jpg" if "jpeg" in mime_type else "png"
        filename = f"{uuid4().hex}.{ext}"
        filepath = join(upload_folder, filename)
        makedirs(upload_folder, exist_ok=True)

        # 保存文件
        with open(filepath, "wb") as f:
            f.write(data)

        return filename


class IPQueryMixIn(RequestMixIn):

    def saintic_ip_query(self, ip: str) -> str:
        """通过 OpenService IP 接口查询 IP 地理位置。

        :param ip: 待查询的 IP 地址
        :returns: 地理位置字符串（"国家, 省份, 城市"），查询失败返回空字符串
        """
        IP_API_URL = "https://hub.saintic.com/openservice/ip/rest"
        if not ip or ip in ("127.0.0.1", "::1", "localhost"):
            return ""
        try:
            resp = self.http(IP_API_URL, params={"ip": ip}, method="get", timeout=3)
            data = resp.json()
        except Exception as e:
            return ""

        if not isinstance(data, dict) or not data.get("success"):
            return ""

        info = data.get("data", {})
        if not isinstance(info, dict) or not info.get("country"):
            return ""

        parts = [info.get(k, "") for k in ("country", "province", "city")]
        ret = ", ".join(p for p in parts if p)
        return "Reserved" if ret.count("Reserved") > 1 else ret

    def ip_api_query(self, ip: str) -> str:
        """通过 ip-api.com 查询 IP 地理位置（降级后备）。

        :param ip: 待查询的 IP 地址
        :returns: 地理位置字符串（"国家, 省份, 城市"），查询失败返回空字符串
        """
        API_URL = f"http://ip-api.com/json/{ip}"
        if not ip or ip in ("127.0.0.1", "::1", "localhost"):
            return ""
        try:
            resp = self.http(API_URL, method="get", timeout=3)
            data = resp.json()
        except Exception as e:
            return ""

        if not isinstance(data, dict) or data.get("status") != "success":
            return ""

        parts = [data.get(k, "") for k in ("country", "regionName", "city")]
        return ", ".join(p for p in parts if p)
