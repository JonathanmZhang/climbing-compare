const PAIRS_URL = "/viewer/data/pairs.json";

async function init() {
  const pairName = new URLSearchParams(location.search).get("pair");
  const backLink = document.getElementById("backLink");
  if (pairName) backLink.href = `index.html?pair=${encodeURIComponent(pairName)}`;

  const res = await fetch(PAIRS_URL);
  const pairs = await res.json();
  const match = pairs.find((p) => p.name === pairName);
  if (!match) {
    document.getElementById("pairSubtitle").textContent = "No pair selected - go back and pick one from the viewer.";
    return;
  }

  const dataRes = await fetch(match.data_path);
  const data = await dataRes.json();
  const dataDir = match.data_path.substring(0, match.data_path.lastIndexOf("/") + 1);

  document.getElementById("pairSubtitle").textContent = `${data.label_a} vs ${data.label_b}`;

  document.getElementById("avgDivergence").textContent = data.summary.avg_divergence.toFixed(1) + "°";

  const peak = data.summary.peak_divergence;
  document.getElementById("peakDivergence").textContent = peak.value.toFixed(1) + "°";
  document.getElementById("peakTimestamps").textContent =
    `${data.label_a} t=${peak.timestamp_a.toFixed(2)}s / ${data.label_b} t=${peak.timestamp_b.toFixed(2)}s`;

  document.getElementById("jointsCompared").textContent = data.summary.joints_compared_count;
  if (data.joints_excluded.length) {
    document.getElementById("jointsExcludedNote").textContent =
      `excluded: ${data.joints_excluded.map((j) => j.joint).join(", ")}`;
  }

  const jointBars = document.getElementById("jointBars");
  const breakdown = data.summary.joint_breakdown;
  const maxValue = Math.max(...breakdown.map((j) => j.avg_divergence));
  for (const joint of breakdown) {
    const row = document.createElement("div");
    row.className = "joint-row";

    const name = document.createElement("div");
    name.textContent = joint.joint.replace(/_/g, " ");

    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${(joint.avg_divergence / maxValue) * 100}%`;
    track.appendChild(fill);

    const value = document.createElement("div");
    value.className = "value";
    value.textContent = joint.avg_divergence.toFixed(1) + "°";

    row.appendChild(name);
    row.appendChild(track);
    row.appendChild(value);
    jointBars.appendChild(row);
  }

  document.getElementById("screenshotA").src = dataDir + data.screenshots.a;
  document.getElementById("screenshotB").src = dataDir + data.screenshots.b;
  document.getElementById("captionA").textContent = `${data.label_a} at t=${peak.timestamp_a.toFixed(2)}s`;
  document.getElementById("captionB").textContent = `${data.label_b} at t=${peak.timestamp_b.toFixed(2)}s`;
}

init();
