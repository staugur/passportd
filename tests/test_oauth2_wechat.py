# -*- coding: utf-8 -*-
"""微信开放平台扫码登录模块测试。"""

import unittest

from passportd.app import create_app


class TestOAuth2Wechat(unittest.TestCase):
    """微信 OAuth2 模块：parse_userinfo 回调等纯函数测试。"""

    @classmethod
    def setUpClass(cls):
        # 先 create_app 触发插件加载（模块顶层会执行 register），再导入模块
        cls.app = create_app()

    def _parse(self, **kwargs):
        from passportd.modules.oauth2_wechat import _parse_wechat_userinfo

        return _parse_wechat_userinfo(**kwargs)

    def test_account_build(self):
        """账号格式为 wechat.{openid}"""
        ret = self._parse(openid="o-abc")
        self.assertEqual(ret["account"], "wechat.o-abc")

    def test_tpid_prefer_unionid(self):
        """有 unionid 时优先使用 unionid，否则退回 openid"""
        ret = self._parse(openid="o-1", unionid="u-9")
        self.assertEqual(ret["tpid"], "u-9")
        ret = self._parse(openid="o-1")
        self.assertEqual(ret["tpid"], "o-1")

    def test_gender_mapping(self):
        """微信性别编码映射：1男→1、2女→0、0/缺失→2"""
        self.assertEqual(self._parse(openid="o", sex=1)["gender"], 1)
        self.assertEqual(self._parse(openid="o", sex=2)["gender"], 0)
        self.assertEqual(self._parse(openid="o", sex=0)["gender"], 2)
        # 兼容字符串形式
        self.assertEqual(self._parse(openid="o", sex="1")["gender"], 1)
        self.assertEqual(self._parse(openid="o", sex="2")["gender"], 0)
        self.assertEqual(self._parse(openid="o")["gender"], 2)

    def test_profile_fields(self):
        """昵称/头像/地区字段解析"""
        ret = self._parse(
            openid="o",
            nickname="张三",
            headimgurl="http://img/1.png",
            province="广东",
            city="深圳",
        )
        self.assertEqual(ret["name"], "张三")
        self.assertEqual(ret["picture"], "http://img/1.png")
        self.assertEqual(ret["location"], "广东 深圳")
        # 空字段回落
        ret = self._parse(openid="o")
        self.assertEqual(ret["name"], "")
        self.assertEqual(ret["picture"], "")
        self.assertEqual(ret["location"], "")


if __name__ == "__main__":
    unittest.main()
