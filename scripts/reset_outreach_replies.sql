-- 返信同期で取り込んだ提案結果をクリアし、送信済み提案を「返信待ち」に戻す。
-- outreach_messages（提案送信履歴）は残す。

DELETE FROM outreach_replies;
