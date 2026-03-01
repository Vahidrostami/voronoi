"""Visualization and HTML report generation for ecosystem simulation."""
from __future__ import annotations

import os


def generate_report(
    history: list[dict],
    extinctions: list[tuple[int, str]],
    territory: dict[str, dict[tuple[int, int], int]],
    output_dir: str = 'output',
) -> str:
    """Generate an HTML report with matplotlib charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    os.makedirs(output_dir, exist_ok=True)

    ticks = [h['tick'] for h in history]
    ants = [h['ants'] for h in history]
    birds = [h['birds'] for h in history]
    fireflies = [h['fireflies'] for h in history]
    wolves = [h['wolves'] for h in history]
    food = [h['total_food'] for h in history]

    # --- Chart 1: Population over time ---
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    ax1.plot(ticks, ants, label='Ants', color='#8B4513', linewidth=1.5)
    ax1.plot(ticks, birds, label='Birds', color='#4169E1', linewidth=1.5)
    ax1.plot(ticks, fireflies, label='Fireflies', color='#FFD700', linewidth=1.5)
    ax1.plot(ticks, wolves, label='Wolves', color='#DC143C', linewidth=1.5)

    # Mark extinction events
    for tick, species in extinctions:
        ax1.axvline(x=tick, color='red', linestyle='--', alpha=0.5)
        ax1.annotate(f'{species} extinct', xy=(tick, ax1.get_ylim()[1] * 0.9),
                     fontsize=8, color='red', rotation=45)

    ax1.set_ylabel('Population')
    ax1.set_title('Population Dynamics')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)

    ax2.plot(ticks, food, label='Food', color='#228B22', linewidth=1.5)
    ax2.set_xlabel('Tick')
    ax2.set_ylabel('Food on Grid')
    ax2.set_title('Food Availability')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    pop_chart_path = os.path.join(output_dir, 'population_chart.png')
    fig.savefig(pop_chart_path, dpi=100)
    plt.close(fig)

    # --- Chart 2: Territory heatmaps ---
    species_config = [
        ('ant', 'Ants Territory', 'YlOrBr'),
        ('bird', 'Birds Territory', 'Blues'),
        ('fireflies', 'Fireflies Territory', 'YlOrRd'),
        ('wolf', 'Wolves Territory', 'Reds'),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 12))
    axes = axes.flatten()

    for idx, (key, title, cmap) in enumerate(species_config):
        grid_data = [[0] * 100 for _ in range(100)]
        for (x, y), count in territory.get(key, {}).items():
            if 0 <= x < 100 and 0 <= y < 100:
                grid_data[y][x] = count

        im = axes[idx].imshow(grid_data, cmap=cmap, interpolation='nearest', aspect='equal')
        axes[idx].set_title(title)
        axes[idx].set_xlabel('X')
        axes[idx].set_ylabel('Y')
        plt.colorbar(im, ax=axes[idx], shrink=0.8)

    plt.tight_layout()
    territory_path = os.path.join(output_dir, 'territory_heatmap.png')
    fig.savefig(territory_path, dpi=100)
    plt.close(fig)

    # --- Generate HTML ---
    total_ticks = len(history)
    final = history[-1] if history else {}
    extinction_list = ''.join(
        f'<li><strong>{species}</strong> went extinct at tick {tick}</li>'
        for tick, species in extinctions
    ) or '<li>No extinctions</li>'

    peak_pop = {}
    for key, label in [('ants', 'Ants'), ('birds', 'Birds'), ('fireflies', 'Fireflies'), ('wolves', 'Wolves')]:
        vals = [h[key] for h in history]
        peak = max(vals) if vals else 0
        peak_tick = vals.index(peak) + 1 if vals else 0
        peak_pop[label] = (peak, peak_tick)

    peak_rows = ''.join(
        f'<tr><td>{label}</td><td>{peak}</td><td>{tick}</td></tr>'
        for label, (peak, tick) in peak_pop.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Ecosystem Simulation Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #fafafa; }}
  h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
  h2 {{ color: #34495e; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
  .stat {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .stat .value {{ font-size: 2em; font-weight: bold; color: #2c3e50; }}
  .stat .label {{ color: #7f8c8d; font-size: 0.9em; }}
  img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin: 10px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; }}
  ul {{ line-height: 1.8; }}
</style>
</head>
<body>
<h1>🌍 Ecosystem Simulation Report</h1>

<div class="stats">
  <div class="stat"><div class="value">{total_ticks}</div><div class="label">Total Ticks</div></div>
  <div class="stat"><div class="value">{final.get('ants', 0) + final.get('birds', 0) + final.get('fireflies', 0) + final.get('wolves', 0)}</div><div class="label">Final Population</div></div>
  <div class="stat"><div class="value">{final.get('total_food', 0)}</div><div class="label">Final Food</div></div>
  <div class="stat"><div class="value">{len(extinctions)}</div><div class="label">Extinctions</div></div>
</div>

<h2>📊 Population Dynamics</h2>
<img src="population_chart.png" alt="Population chart">

<h2>🏆 Peak Populations</h2>
<table>
<tr><th>Species</th><th>Peak Population</th><th>At Tick</th></tr>
{peak_rows}
</table>

<h2>💀 Extinction Events</h2>
<ul>{extinction_list}</ul>

<h2>🗺️ Territory Heatmaps</h2>
<p>Density of species presence over the simulation run:</p>
<img src="territory_heatmap.png" alt="Territory heatmaps">

<h2>📈 Final State</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Ants</td><td>{final.get('ants', 0)}</td></tr>
<tr><td>Birds</td><td>{final.get('birds', 0)}</td></tr>
<tr><td>Fireflies</td><td>{final.get('fireflies', 0)}</td></tr>
<tr><td>Wolves</td><td>{final.get('wolves', 0)}</td></tr>
<tr><td>Food</td><td>{final.get('total_food', 0)}</td></tr>
</table>

<footer style="margin-top:40px;color:#95a5a6;font-size:0.9em;">
Generated by Multi-Species Ecosystem Simulation
</footer>
</body>
</html>"""

    report_path = os.path.join(output_dir, 'report.html')
    with open(report_path, 'w') as f:
        f.write(html)

    print(f"HTML report saved to: {report_path}")
    print(f"Charts: {pop_chart_path}, {territory_path}")
    return report_path
