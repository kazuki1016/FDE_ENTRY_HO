"""AC-3: 回答品質の受け入れ基準を検証する（spec.md 5章）。実APIを呼び出す。"""
from generator import generate_answer

_FDE_CHUNK = {
    "content": "FDE（Forward Deployed Engineer）とは、顧客や現場の最前線に入り込み、"
    "課題の発見から実装・運用までを一気通貫で担うエンジニアです。",
    "section_number": "Section 0",
    "page_number": 9,
    "title": "FDEとは何か",
}


def test_日本語で参照ページ付きの回答が返ること():
    answer = generate_answer("FDEとは何ですか？", [_FDE_CHUNK])

    assert answer
    assert any("あ" <= ch <= "ん" or "ア" <= ch <= "ン" or "一" <= ch <= "龥" for ch in answer)  # AC-3-3
    assert "9" in answer  # 参照元ページ番号の付記


def test_コンテキスト外の質問には該当情報なしの文言が返ること():
    answer = generate_answer("この講座に関係ない質問です。今日の天気は？", [_FDE_CHUNK])

    assert "講座内容に該当する情報がありません" in answer  # AC-3-2
