# このリポジトリでの作業ガイド

## プロジェクト概要

- このプロジェクトは、XeFM 向けに PDF の結合・ページ範囲の抽出・回転を提供する Python 拡張です。
- 拡張機能の定義は `xefm-extension.toml`、XeFM のアクションは `xefm_pdftool/actions.py`、PDF 操作ロジックは `xefm_pdftool/logic.py` にあります。
- 機能や使い方の詳細は `README.md` を参照してください。

## XeFM との互換性

- XeFM の API、拡張機能形式、メニュー連携に関わる変更では、現行の仕様を https://github.com/crftwr/xefm で確認してください。必要に応じて公式ドキュメントも参照し、古い記憶や推測だけで API の挙動を決めないでください。
- 参照先を確認できない場合は、その制約を明記し、未確認の仕様を事実として扱わないでください。
- アクション ID、Python の import パス、パッケージ名、テスト名などを変更するときは、`xefm-extension.toml`、`pyproject.toml`、テスト、README の参照も合わせて確認してください。

## 実装上の注意

- PDF の処理は可能な限り `xefm_pdftool/logic.py` に置き、XeFM 固有の入出力や UI 操作は `xefm_pdftool/actions.py` に置いてください。
- 元の PDF を変更しないこと、出力先を明示的に扱うこと、既存ファイルを置き換える場合は確認することを維持してください。
- 変更に直接関係するテストとドキュメントを更新し、無関係な変更は避けてください。

## テストと検証

依存関係の同期、テスト、拡張機能定義の検査には次のコマンドを使ってください（PowerShell、リポジトリのルートで実行）。

```powershell
uv sync
uv run python -m pytest
xefm ext check .
```

XeFM の拡張機能 API やパッケージ構成を変更した場合は、可能ならパッケージもビルドして確認してください。

```powershell
uv build
```
