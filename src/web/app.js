const form = document.querySelector("#question-form");
const sessionSelect = document.querySelector("#session");
const sessionStatus = document.querySelector("#session-status");
const submitButton = document.querySelector("#submit-button");
const answerStatus = document.querySelector("#answer-status");
const answer = document.querySelector("#answer");
const resetButton = document.querySelector("#reset-button");
const initialAnswerStatus = answerStatus.textContent;

async function loadSessions() {
  try {
    const response = await fetch("/api/v1/sessions");
    if (!response.ok) {
      throw new Error("無法取得會期，請重新整理頁面再試。");
    }

    const sessions = await response.json();
    sessionSelect.replaceChildren();
    if (sessions.length === 0) {
      sessionStatus.textContent = "目前沒有可用的會期資料。";
      return;
    }

    for (const session of sessions) {
      const option = document.createElement("option");
      option.value = session.id;
      option.textContent = session.name;
      sessionSelect.append(option);
    }
    sessionSelect.disabled = false;
    submitButton.disabled = false;
    sessionStatus.textContent = `目前有 ${sessions.length} 個可用會期。`;
  } catch (error) {
    sessionStatus.textContent = error.message;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.querySelector("#question").value.trim();
  if (!sessionSelect.value || !question) {
    answerStatus.textContent = "請選擇會期並輸入問題。";
    return;
  }

  const payload = {
    session_id: sessionSelect.value,
    question,
    member_name: document.querySelector("#member-name").value.trim() || "all",
    geographical_scope: document.querySelector("#geographical-scope").value,
    committee: document.querySelector("#committee").value.trim() || "all",
  };

  submitButton.disabled = true;
  resetButton.hidden = true;
  answer.textContent = "";
  answerStatus.textContent = "正在查詢，首次建立索引可能需要較長時間…";

  try {
    const response = await fetch("/api/v1/questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(typeof result.detail === "string" ? result.detail : "查詢失敗，請稍後再試。");
    }
    answer.textContent = result.answer;
    answerStatus.textContent = "查詢完成。";
  } catch (error) {
    answerStatus.textContent = error.message || "無法連線，請稍後再試。";
  } finally {
    submitButton.disabled = false;
    resetButton.hidden = false;
  }
});

resetButton.addEventListener("click", () => {
  form.reset();
  sessionSelect.selectedIndex = 0;
  answer.textContent = "";
  answerStatus.textContent = initialAnswerStatus;
  resetButton.hidden = true;
  window.scrollTo(0, 0);
});

loadSessions();
