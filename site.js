const asset = (task, condition) => `assets/scenes/${task}--${condition}.webp`;
const select = document.querySelector("#task");
const scenes = [...document.querySelectorAll("[data-condition]")];

function updateScenes() {
  const label = select.selectedOptions[0].textContent;
  for (const scene of scenes) {
    const image = scene.querySelector("img");
    const condition = scene.querySelector("figcaption").textContent;
    image.alt = `${label}, ${condition.toLowerCase()}`;
    image.src = asset(select.value, scene.dataset.condition);
  }
  document.querySelector("#scene-status").textContent = `Showing four scenes for ${label}.`;
}
select.addEventListener("change", updateScenes);

const success = [...document.querySelectorAll("#results-body tr")].map((row) =>
  [...row.querySelectorAll("td")].map((cell) => cell.textContent)
);
const score = [
  ["70.6", "23.3", "17.2", "27.2", "48.0"],
  ["73.2", "36.8", "40.9", "34.3", "35.8"],
  ["62.7", "17.8", "8.0", "13.0", "49.8"],
  ["68.8", "18.0", "13.2", "6.7", "56.2"],
  ["66.3", "63.3", "57.0", "51.3", "9.1"],
];

const metricButtons = [...document.querySelectorAll("[data-metric]")];
for (const button of metricButtons) {
  button.addEventListener("click", () => {
    const showScore = button.dataset.metric === "score";
    for (const other of metricButtons) other.setAttribute("aria-pressed", String(other === button));
    const values = showScore ? score : success;
    for (const [index, row] of [...document.querySelectorAll("#results-body tr")].entries()) {
      for (const [column, cell] of [...row.querySelectorAll("td")].entries()) {
        cell.textContent = values[index][column];
      }
    }
    document.querySelector("#metric-caption").textContent =
      showScore ? "Task score by scene condition" : "Success rate (%) by scene condition";
    document.querySelector("#metric-note").textContent = showScore
      ? "Native task scores are scaled to 0–100. Mean drop is in score points."
      : "Success rates are percentages. Mean drop is the average decrease across the three mirror conditions, in percentage points.";
  });
}

for (const media of document.querySelectorAll(".diagnostic-media")) {
  const video = media.querySelector("video");
  const outcome = media.querySelector(".video-outcome");
  const completion = media.dataset.completedAt;
  const completionTime = Number(completion);

  function updateOutcome() {
    const complete = completion === "ended" ? video.ended : video.currentTime >= completionTime;
    if (outcome.hidden === complete) outcome.hidden = !complete;
  }

  for (const event of ["timeupdate", "seeking", "seeked", "ended", "play", "emptied"]) {
    video.addEventListener(event, updateOutcome);
  }
  if (completion !== "ended" && "requestVideoFrameCallback" in video) {
    const updateOnFrame = () => {
      updateOutcome();
      video.requestVideoFrameCallback(updateOnFrame);
    };
    video.requestVideoFrameCallback(updateOnFrame);
  }
  updateOutcome();
}

const citation = document.querySelector("#bibtex");
const copyCitation = document.querySelector("#copy-citation");
const citationStatus = document.querySelector("#citation-status");

copyCitation.hidden = false;
copyCitation.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(citation.textContent.trim());
    citationStatus.textContent = "BibTeX copied.";
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(citation);
    selection.removeAllRanges();
    selection.addRange(range);
    citationStatus.textContent = "BibTeX selected. Use your system’s copy shortcut to copy it.";
  }
});
