/*!
 * password-encrypt.js - 前端密码 JWE 加密工具
 *
 * 使用 WebCrypto (RSA-OAEP + A256GCM) 生成与后端 joserfc 兼容的
 * JWE 紧凑序列化密文，用于登录 / 注册表单的密码加密传输。
 *
 * 用法（先引入 jQuery）：
 *   PassportEncrypt.encryptPassword('明文密码').then(function (jwe) {
 *     // jwe 形如 "eyJhbGciOiJSU0EtT0FFUCIsImVuYyI6IkEyNTZHQ00ifQ.xxx.yyy.zzz.ttt"
 *   });
 *
 * 公钥从后端 /api/key 获取（默认路径可在模板中通过 window.PASSPORT_KEY_URL 覆盖）。
 */
(function (global) {
    'use strict';

    let cachedKey = null;

    /** base64url 编码（Uint8Array/ArrayBuffer -> 无填充 base64url 字符串） */
    function b64urlEncode(input) {
        let bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary)
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=+$/, '');
    }

    /** 解析 PEM 公钥 -> SPKI ArrayBuffer */
    function pemToArrayBuffer(pem) {
        let b64 = pem
            .replace('-----BEGIN PUBLIC KEY-----', '')
            .replace('-----END PUBLIC KEY-----', '')
            .replace(/\s+/g, '');
        let binary = atob(b64);
        let len = binary.length;
        let bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    /** 获取 RSA 公钥信息（带缓存）：{header, key} */
    function getPublicKey() {
        if (cachedKey) {
            return Promise.resolve(cachedKey);
        }
        let keyUrl = global.PASSPORT_KEY_URL || '/api/key';
        return new Promise(function (resolve, reject) {
            $.ajax({
                url: keyUrl,
                method: 'GET',
                dataType: 'json',
                success: function (res) {
                    if (res && res.success && res.data && res.data.key) {
                        cachedKey = res.data;
                        resolve(res.data);
                    } else {
                        reject(new Error('failed to fetch public key'));
                    }
                },
                error: function () {
                    reject(new Error('failed to fetch public key'));
                }
            });
        });
    }

    /**
     * 加密明文密码为 JWE 紧凑字符串。
     *
     * @param {string} plaintext 待加密的明文（密码）
     * @returns {Promise<string>} JWE 紧凑序列化密文
     * @throws 浏览器不支持 WebCrypto 或获取公钥失败时 reject
     */
    function encryptPassword(plaintext) {
        if (!global.crypto || !global.crypto.subtle) {
            return Promise.reject(new Error('WebCrypto is not supported'));
        }
        return getPublicKey().then(function (keyInfo) {
            let cryptoSubtle = global.crypto.subtle;
            let spki = pemToArrayBuffer(keyInfo.key);

            return cryptoSubtle
                .importKey(
                    'spki',
                    spki,
                    { name: 'RSA-OAEP', hash: 'SHA-1' },
                    false,
                    ['encrypt']
                )
                .then(function (publicKey) {
                    let protectedB64 = b64urlEncode(
                        new TextEncoder().encode(JSON.stringify(keyInfo.header))
                    );
                    // JWE 紧凑格式的 AAD = ASCII(BASE64URL(protected header))
                    let aad = new TextEncoder().encode(protectedB64);

                    let cek = crypto.getRandomValues(new Uint8Array(32));
                    let iv = crypto.getRandomValues(new Uint8Array(12));

                    // 1. RSA-OAEP 加密 CEK
                    return cryptoSubtle
                        .encrypt({ name: 'RSA-OAEP' }, publicKey, cek)
                        .then(function (encryptedKeyBuf) {
                            let encryptedKey = new Uint8Array(encryptedKeyBuf);

                            // 2. A256GCM 加密明文（附加认证数据 AAD）
                            return cryptoSubtle
                                .importKey(
                                    'raw',
                                    cek,
                                    { name: 'AES-GCM' },
                                    false,
                                    ['encrypt']
                                )
                                .then(function (aesKey) {
                                    return cryptoSubtle.encrypt(
                                        {
                                            name: 'AES-GCM',
                                            iv: iv,
                                            additionalData: aad
                                        },
                                        aesKey,
                                        new TextEncoder().encode(plaintext)
                                    );
                                })
                                .then(function (ctTagBuf) {
                                    let ctTag = new Uint8Array(ctTagBuf);
                                    let ciphertext = ctTag.slice(0, ctTag.length - 16);
                                    let tag = ctTag.slice(ctTag.length - 16);

                                    // 3. 拼接 compact JWE: protected.encrypted_key.iv.ciphertext.tag
                                    return [
                                        protectedB64,
                                        b64urlEncode(encryptedKey),
                                        b64urlEncode(iv),
                                        b64urlEncode(ciphertext),
                                        b64urlEncode(tag)
                                    ].join('.');
                                });
                        });
                });
        });
    }

    global.PassportEncrypt = {
        encryptPassword: encryptPassword,
        getPublicKey: getPublicKey
    };
})(window);
