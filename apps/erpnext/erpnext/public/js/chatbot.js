frappe.ready(() => {
    const chatBox = document.createElement("div");
    chatBox.innerHTML = `
      <div id="chat-box" style="
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 300px;
        height: 400px;
        background: white;
        border: 1px solid #ccc;
        z-index: 9999;
      ">
        <div style="padding:10px; background:#eee">Chat</div>
        <div id="chat-content" style="height:300px; overflow:auto"></div>
        <input id="chat-input" style="width:100%" placeholder="Type..."/>
      </div>
    `;
    document.body.appendChild(chatBox);
  });