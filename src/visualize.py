"""Generate HTML report with matplotlib charts for the ecosystem simulation."""

import os
import base64
import io


def generate_report(history: list[dict], extinction_events: list[tuple[int, str]],
                    heatmaps: dict[str, list[list[int]]],
                    output_path: str = 'output/report.html') -> None:
    """Generate an HTML report with population charts and territory heatmaps."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    ticks = [r['tick'] for r in history]
    species_colors = {'ant': '#e6550d', 'bird': '#3182bd',
                      'firefly': '#fdae6b', 'wolf': '#636363'}

    # Chart 1: Population over time
    fig1, ax1 = plt.subplots(figsize=(12, 5))
    for sp, color in species_colors.items():
        vals = [r[sp] for r in history]
        ax1.plot(ticks, vals, label=sp.capitalize(), color=color, linewidth=1.5)

    # Mark extinction events
    for tick, sp in extinction_events:
        ax1.axvline(x=tick, color=species_colors[sp], linestyle='--', alpha=0.5)
        ax1.annotate(f'{sp} extinct', xy=(tick, 0), fontsize=8,
                     color=species_colors[sp], rotation=90, va='bottom')

    ax1.set_xlabel('Tick')
    ax1.set_ylabel('Population')
    ax1.set_title('Population Dynamics Over Time')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    pop_img = _fig_to_base64(fig1)
    plt.close(fig1)

    # Chart 2: Food supply over time
    fig2, ax2 = plt.subplots(figsize=(12, 3))
    food_vals = [r['food'] for r in history]
    ax2.fill_between(ticks, food_vals, alpha=0.3, color='green')
    ax2.plot(ticks, food_vals, color='green', linewidth=1)
    ax2.set_xlabel('Tick')
    ax2.set_ylabel('Food Count')
    ax2.set_title('Food Supply Over Time')
    ax2.grid(True, alpha=0.3)
    food_img = _fig_to_base64(fig2)
    plt.close(fig2)

    # Chart 3: Cumulative territory heatmaps
    fig3, axes = plt.subplots(2, 2, figsize=(12, 10))
    species_list = ['ant', 'bird', 'firefly', 'wolf']
    for idx, sp in enumerate(species_list):
        ax = axes[idx // 2][idx % 2]
        full_map = heatmaps.get(sp, [[0] * 100 for _ in range(100)])
        h = len(full_map)
        w = len(full_map[0]) if h > 0 else 100
        # Downsample to 50x50 for visibility
        ds = max(1, w // 50)
        sh = h // ds
        sw = w // ds
        small = [[0] * sw for _ in range(sh)]
        for y in range(h):
            for x in range(w):
                small[y // ds][x // ds] += full_map[y][x]
        ax.imshow(small, cmap='hot', interpolation='nearest', aspect='equal')
        ax.set_title(f'{sp.capitalize()} Territory (cumulative)')
        ax.set_xlabel('x')
        ax.set_ylabel('y')
    fig3.suptitle('Territory Heatmaps — Where Each Species Spent Most Time', fontsize=14)
    fig3.tight_layout()
    heat_img = _fig_to_base64(fig3)
    plt.close(fig3)

    # Build HTML
    final = history[-1] if history else {}
    ext_html = ''
    if extinction_events:
        ext_html = '<ul>' + ''.join(
            f'<li><strong>{sp.capitalize()}</strong> went extinct at tick {t}</li>'
            for t, sp in extinction_events
        ) + '</ul>'
    else:
        ext_html = '<p>No extinctions occurred during the simulation.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Ecosystem Simulation Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         max-width: 900px; margin: 40px auto; padding: 0 20px;
         color: #333; background: #fafafa; }}
  h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
  h2 {{ color: #2c3e50; margin-top: 30px; }}
  img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; margin: 10px 0; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
  .stat {{ background: white; padding: 15px; border-radius: 8px;
           box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
  .stat .number {{ font-size: 2em; font-weight: bold; }}
  .stat .label {{ color: #666; font-size: 0.9em; }}
  .ant {{ color: #e6550d; }}
  .bird {{ color: #3182bd; }}
  .firefly {{ color: #fdae6b; }}
  .wolf {{ color: #636363; }}
</style>
</head>
<body>
<h1>🌍 Ecosystem Simulation Report</h1>

<h2>Final Population (Tick {final.get('tick', 0)})</h2>
<div class="stats">
  <div class="stat"><div class="number ant">{final.get('ant', 0)}</div><div class="label">Ants</div></div>
  <div class="stat"><div class="number bird">{final.get('bird', 0)}</div><div class="label">Birds</div></div>
  <div class="stat"><div class="number firefly">{final.get('firefly', 0)}</div><div class="label">Fireflies</div></div>
  <div class="stat"><div class="number wolf">{final.get('wolf', 0)}</div><div class="label">Wolves</div></div>
</div>

<h2>Extinction Events</h2>
{ext_html}

<h2>Population Dynamics</h2>
<img src="data:image/png;base64,{pop_img}" alt="Population over time">

<h2>Food Supply</h2>
<img src="data:image/png;base64,{food_img}" alt="Food supply over time">

<h2>Territory Heatmaps</h2>
<img src="data:image/png;base64,{heat_img}" alt="Territory heatmaps">

<p><em>Generated by Ecosystem Simulation</em></p>
</body>
</html>"""

    with open(output_path, 'w') as f:
        f.write(html)


def _fig_to_base64(fig) -> str:
    """Convert a matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')
