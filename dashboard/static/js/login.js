const c = document.getElementById("stars");
const ctx = c.getContext("2d");
let w, h, stars;
function resize() {
  w = c.width = innerWidth;
  h = c.height = innerHeight;
  stars = Array.from({ length: 140 }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: Math.random() * 1.6,
    v: 0.15 + Math.random() * 0.45,
  }));
}
function tick() {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "rgba(243,193,107,0.85)";
  stars.forEach((s) => {
    s.y -= s.v;
    if (s.y < 0) s.y = h;
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fill();
  });
  requestAnimationFrame(tick);
}
addEventListener("resize", resize);
resize();
tick();
