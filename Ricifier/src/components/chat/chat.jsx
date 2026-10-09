import { useState } from "react";
import "./chat.css";

const Chat = () => {
    const [message, setMessage] = useState("");
    const [messages, setMessages] = useState([]);

    const sendMessage = (e) => {
        e.preventDefault();

        if (!message.trim()) return;

        setMessages([
        ...messages,
        {
            id: Date.now(),
            text: message,
            sender: "You",
        },
        ]);

        setMessage("");
    };

    return (
        <div className="chat-container">
        <div className="chat-header">
            <h2>Simple Chat</h2>
            <p>Chat with your friends</p>
        </div>

        <div className="chat-messages">
            {messages.length === 0 && (
            <p className="empty-message">
                No messages yet. Say hello!
            </p>
            )}

            {messages.map((msg) => (
            <div key={msg.id} className="message-row">
                <div className="message-bubble">
                <span className="sender">{msg.sender}</span>
                <p>{msg.text}</p>
                </div>
            </div>
            ))}
        </div>

        <form className="chat-input" onSubmit={sendMessage}>
            <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Type a message..."
            />

            <button type="submit">Send</button>
        </form>
        </div>
    );
}

export default Chat;