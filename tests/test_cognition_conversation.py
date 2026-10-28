import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from gaia.cognition.conversation import ConversationStore,project_history
from gaia.cognition.schema import seal


class ConversationTests(unittest.TestCase):
    def count(self,text):return len(text.encode())

    def test_history_persists_across_store_reopen(self):
        with tempfile.TemporaryDirectory()as state:
            first=ConversationStore(state);conversation=first.create('persistent fixture')
            one=first.append(conversation['id'],'USER','remember alpha')
            two=first.append(conversation['id'],'ASSISTANT','alpha recorded as untrusted data')
            history=ConversationStore(state).history(conversation['id'])
            self.assertEqual([v['id']for v in history],[one['id'],two['id']])
            self.assertEqual([v['payload']['sequence']for v in history],[1,2])

    def test_fork_and_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory()as state:
            conversations=ConversationStore(state);conversation=conversations.create('fixture')
            first=conversations.append(conversation['id'],'USER','first')
            fork=seal('CHAT_TURN',{**first['payload'],'content':'fork','content_sha256':'bad'})
            conversations.store.put(fork)
            with self.assertRaisesRegex(ValueError,'FORK'):
                conversations.history(conversation['id'])
            path=conversations.store.path('CHAT_TURN',first['id']);path.chmod(0o644)
            data=json.loads(path.read_text());data['payload']['content']='changed';path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):conversations.store.get(first['id'],'CHAT_TURN')

    def test_projection_keeps_newest_complete_turns(self):
        turns=[seal('CHAT_TURN',{'role':'USER','content':text})for text in ('old '*20,'middle '*8,'new')]
        newest_size=self.count(json.dumps([{'role':'user','content':'new'}],separators=(',',':')))
        value=project_history(turns,self.count,newest_size+4,reserve=4)
        self.assertEqual([v['payload']['content']for v in value['turns']],['new'])
        self.assertEqual(len(value['excluded']),2)

    def test_private_and_action_authority_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory()as state:
            conversations=ConversationStore(state);conversation=conversations.create('fixture')
            with self.assertRaises(ValueError):conversations.append(conversation['id'],'SYSTEM','run shell')
            with self.assertRaises(ValueError):conversations.append(conversation['id'],'USER','password=secret-value')

    def test_cli_persists_and_reopens_history_without_inference(self):
        root=Path(__file__).resolve().parents[1]
        python=sys.executable
        with tempfile.TemporaryDirectory()as state:
            created=subprocess.run([python,'-B',str(root/'gaia.py'),'cognitive-conversation',
                '--state-dir',state,'--label','cli fixture'],capture_output=True,text=True,check=True)
            identifier=json.loads(created.stdout)['id']
            subprocess.run([python,'-B',str(root/'gaia.py'),'cognitive-chat-append','--state-dir',state,
                identifier,'--role','USER','--content','persistent hello'],capture_output=True,text=True,check=True)
            shown=subprocess.run([python,'-B',str(root/'gaia.py'),'cognitive-chat-history','--state-dir',state,
                identifier],capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(shown.stdout)[0]['payload']['content'],'persistent hello')


if __name__=='__main__':unittest.main()
