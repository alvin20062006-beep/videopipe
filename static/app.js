const $ = (selector) => document.querySelector(selector);
const state = { text: "", video: null, quality: "720", jobs: new Map() };
const linkInput = $("#link-input");
const clearButton = $("#clear-button");

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "时长未知";
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json().catch(() => ({ detail: "服务器返回了无法识别的响应" }));
  if (!response.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function showVideo(video) {
  state.video = video;
  if (!video.qualities.some((quality) => quality.id === state.quality && quality.available !== false)) state.quality = "best";
  $("#thumbnail").src = video.thumbnail || "";
  $("#thumbnail-duration").textContent = formatDuration(video.duration);
  $("#video-title").textContent = video.title;
  $("#platform").textContent = video.platform;
  $("#duration").textContent = formatDuration(video.duration);
  $("#qualities").replaceChildren(...video.qualities.map((quality) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `quality${quality.id === state.quality ? " selected" : ""}`;
    button.disabled = quality.available === false;
    button.innerHTML = `<strong>${quality.label}</strong><span>${quality.detail}</span>`;
    button.addEventListener("click", () => {
      state.quality = quality.id;
      document.querySelectorAll(".quality").forEach((item) => item.classList.toggle("selected", item === button));
    });
    return button;
  }));
  $("#result").hidden = false;
}

linkInput.addEventListener("input", () => { clearButton.hidden = !linkInput.value; });
clearButton.addEventListener("click", () => {
  linkInput.value = "";
  clearButton.hidden = true;
  linkInput.focus();
});

$("#analyze-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.text = linkInput.value.trim();
  $("#message").textContent = "正在解析链接…";
  $("#analyze-button").disabled = true;
  try {
    showVideo(await api("/api/analyze", { method: "POST", body: JSON.stringify({ text: state.text }) }));
    $("#message").textContent = "";
  } catch (error) {
    $("#message").textContent = error.message;
    $("#result").hidden = true;
  } finally {
    $("#analyze-button").disabled = false;
  }
});

$("#reset-button").addEventListener("click", () => {
  $("#result").hidden = true;
  linkInput.select();
});

$("#download-button").addEventListener("click", async () => {
  $("#download-button").disabled = true;
  $("#tasks").hidden = false;
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify({
      text: state.text,
      quality: state.quality,
      title: state.video.title,
      thumbnail: state.video.thumbnail,
      platform: state.video.platform,
      resolved_url: state.video.resolved_url,
      headers: state.video.headers,
    }) });
    const row = addJobRow(job);
    pollJob(job.id, row);
  } catch (error) {
    $("#message").textContent = error.message;
  } finally {
    $("#download-button").disabled = false;
  }
});

function addJobRow(job) {
  if (state.jobs.has(job.id)) return state.jobs.get(job.id);
  const row = document.createElement("div");
  row.className = "job-row";
  row.dataset.jobId = job.id;
  row.innerHTML = `
    <img alt="">
    <div class="job-copy"><strong></strong><span></span></div>
    <div class="job-progress">
      <div class="steps"><span data-step="download">正在下载</span><span data-step="complete">下载完成</span></div>
      <div class="progress-line"><i></i></div>
    </div>
    <div class="job-end"><strong class="progress-text">0%</strong><button type="button" aria-label="取消或移除任务">×</button></div>`;
  row.querySelector("img").src = job.thumbnail || "";
  row.querySelector(".job-copy strong").textContent = job.title;
  row.querySelector(".job-copy span").textContent = job.quality === "best" ? "最佳画质" : `${job.quality}P`;
  $("#job-list").append(row);
  state.jobs.set(job.id, row);
  row.dataset.status = job.status;
  row.querySelector(".job-end button").addEventListener("click", async () => {
    try {
      if (["completed", "failed", "cancelled", "delivered"].includes(row.dataset.status)) {
        await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
        state.jobs.delete(job.id);
        row.remove();
        $("#task-count").textContent = state.jobs.size;
        $("#tasks").hidden = !state.jobs.size;
      } else {
        row.querySelector(".job-end button").disabled = true;
        row.querySelector('[data-step="download"]').textContent = "正在停止";
        await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      }
    } catch (error) {
      $("#message").textContent = error.message;
    }
  });
  $("#task-count").textContent = state.jobs.size;
  $("#tasks").hidden = false;
  return row;
}

async function pollJob(id, row) {
  try {
    const job = await api(`/api/jobs/${id}`);
    const status = job.status;
    row.dataset.status = status;
    const progress = status === "completed" ? 100 : job.progress || 0;
    row.querySelector(".progress-line i").style.width = `${progress}%`;
    row.querySelector(".progress-text").textContent = `${Math.round(progress)}%`;
    row.querySelectorAll(".steps span").forEach((step) => step.classList.remove("current"));
    const step = status === "completed" ? "complete" : "download";
    row.querySelector(`[data-step="${step}"]`).classList.add("current");
    if (status === "cancelling") {
      row.querySelector('[data-step="download"]').textContent = "正在停止";
      row.querySelector(".job-end button").disabled = true;
    }
    if (status === "completed" && !row.dataset.downloaded) {
      row.dataset.downloaded = "true";
      window.location.assign(`/api/jobs/${id}/file`);
      return;
    }
    if (status === "cancelled") {
      row.querySelector('[data-step="download"]').textContent = "已停止";
      row.querySelector('[data-step="complete"]').textContent = "未完成";
      row.querySelector(".job-end button").disabled = false;
      row.classList.add("failed");
      return;
    }
    if (status === "failed") {
      row.querySelector('[data-step="download"]').textContent = "下载失败";
      row.querySelector('[data-step="complete"]').textContent = "未完成";
      row.querySelector(".job-end button").disabled = false;
      row.classList.add("failed");
      $("#message").textContent = job.error || "下载失败";
      return;
    }
    if (status === "delivered") return;
    setTimeout(() => pollJob(id, row), 800);
  } catch (error) {
    $("#message").textContent = error.message;
    row.classList.add("failed");
  }
}

async function restoreJobs() {
  try {
    const jobs = await api("/api/jobs");
    jobs.forEach((job) => {
      const row = addJobRow(job);
      if (job.status !== "delivered") pollJob(job.id, row);
    });
  } catch (error) {
    $("#message").textContent = error.message;
  }
}

restoreJobs();
