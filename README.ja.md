# bedrock-env

AWS SSO プロファイルから [Amazon Bedrock の短期 API キー](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html)を生成します。開発サーバーのように長時間動くプロセスには、キーの期限が切れる前に新しいキーを渡し続けます。

```sh
# 現在のシェルに AWS_BEARER_TOKEN_BEDROCK を設定する
eval "$(bedrock-env export --profile my-sso-profile)"

# コマンドを起動し、キーの期限が切れる前に新しいキーで再起動する
bedrock-env run --profile my-sso-profile -- uv run uvicorn app:app --reload
```

## 背景

短期 API キーの実体は、手元の AWS 認証情報で署名した SigV4 の presigned URL です。生成はローカルで完結し、AWS API は呼びません。キーは次のどちらか早いほうで失効します。

- 指定した有効期間（最大 12 時間）
- 署名に使った認証情報の有効期限

SSO プロファイルでは通常、後者で失効します。ロールの認証情報の有効期限は許可セットのセッション時間（1 時間に設定されていることが多い）で決まるため、手動で export したキーを使う開発サーバーは、1 時間ほどで 403 を返すようになります。

起動中のプロセスの環境変数は外部から書き換えられません。そこで `bedrock-env run` はコマンドを子プロセスとして管理し、キーが失効する少し前に新しいキーで再起動します。

## インストール

```sh
uv tool install git+https://github.com/<owner>/bedrock-env
```

Python 3.10 以上、macOS / Linux で動作します。

## 使い方

### `bedrock-env export`

```sh
eval "$(bedrock-env export --profile my-sso-profile)"          # bash / zsh
bedrock-env export --profile my-sso-profile --format fish | source
bedrock-env export --format dotenv > .env.bedrock
bedrock-env export --format json
```

有効期限は標準エラー出力に表示します。

### `bedrock-env run -- COMMAND...`

`AWS_BEARER_TOKEN_BEDROCK` を設定して `COMMAND` を起動します。`AWS_REGION` が未設定の場合は、キーを生成したリージョンを設定します。キーの失効が近づくと、次の手順で再起動します。

1. 新しいキーを生成する
2. コマンドのプロセスグループに `SIGTERM` を送る（`--stop-timeout` 秒経っても終了しなければ `SIGKILL` を送る）
3. 新しいキーでコマンドを起動し直す

`bedrock-env` が受け取った `SIGINT` / `SIGTERM` / `SIGHUP` はコマンドに転送します。コマンドが自ら終了した場合は再起動せず、同じ終了コードで終了します。

オプションは [README.md](README.md#bedrock-env-run----command) の表を参照してください。

### SSO セッションが切れたとき

`aws sso login` で得た SSO セッションにも有効期限があります。期限が切れると、新しいロール認証情報を取得できません。

- `bedrock-env run` は実行中のプロセスを止めません。ログに `aws sso login` の実行を促すメッセージを出し、`--retry-interval` ごとにキーの生成を再試行します。別のターミナルでログインすれば、次の再試行で新しいセッションを使います。
- `--auto-login` を指定した場合は、`aws sso login --profile ...` を自動で実行します（ブラウザが開きます）。

## 注意点

- 再起動中に処理していたリクエストは失敗します。SSO を使う場合、再起動は許可セットのセッション時間ごとに 1 回起こります。
- キーは生成したリージョンでのみ有効です。
- 新しいキーを受け取るのは `bedrock-env run` で起動したプロセスだけです。`export` を実行したシェルでは、もう一度実行する必要があります。
- Windows は対象外です。

アプリケーションが AWS SDK を直接使っている場合は、API キーを使わずに SSO プロファイルで SigV4 署名するほうが簡単です。認証情報の更新は SDK が行います。API キーが役立つのは、主に Bearer トークンしか受け付けないツールや SDK を使う場合です。
