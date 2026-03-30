// NeuralClaw Desktop — Chat Page

import ChatView from '../components/chat/ChatView';
import Header from '../components/layout/Header';

export default function ChatPage() {
  return (
    <>
      <Header title="Chat" />
      <div className="app-content" style={{ display: 'flex', flexDirection: 'column' }}>
        <ChatView />
      </div>
    </>
  );
}
