## oidc

redirect_uri=http://localhost:10030/callback

### register/login

curl -iL "http://localhost:10030/user/signup" -d account=test -d encrypted_password=<jwe> -d encrypted_repassword=<jwe>
> 302 to signin

curl -iL "http://localhost:10030/user/signin" -d account=test -d encrypted_password=<jwe>
> 302 with cookie(sid)

### test login state

curl -i -H "Authorization: sid $sid" http://localhost:10030
> bool

### register oauth client

curl -i -H "Authorization: sid $sid" "http://localhost:10030/api/oidc/client" -d name=test -d scope=openid -d redirect_uri=${redirect_uri}
> dict result: client_id/client_secret
> set env var

### test oauth process

curl -iL -H "Authorization: sid $sid" "http://localhost:10030/oidc/authorize?response_type=code&client_id=${client_id}&redirect_uri=${redirect_uri}&scope=openid" -d action=approve
> dict result: code
> set env var

curl -X POST http://localhost:10030/oidc/token -d client_id=${client_id} -d client_secret=${client_secret} -d grant_type=authorization_code -d redirect_uri=${redirect_uri} -d code=$code
> dict result: token
> set env var

### test ak

curl -iL -H "Authorization: Bearer $ak" "http://localhost:10030/oidc/userinfo"

