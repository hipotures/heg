mod bank;
mod cycles;
mod exact_verify;
mod graph;
mod large_verify;
mod lns;
mod mutation;
mod protocol;
mod rng;
mod search;
mod spectral;
mod voltage_bipartite;

use std::env;
use std::process;
use std::time::Instant;

use crate::cycles::{
    DfsScratch, ObjectiveMode, evaluate_lengths, forbidden_lengths, score_graph_fast,
};
use crate::graph::BitGraph;
use crate::mutation::{GraphMode, SeedStyle, WitnessCache, generate_seed, mutate};
use crate::rng::Rng;
use crate::search::{Algorithm, SearchParams, run_parallel};

fn format_counts_json(counts: &[(u16, u32)]) -> String {
    let parts: Vec<String> = counts
        .iter()
        .map(|(l, c)| format!("\"{l}\":{c}"))
        .collect();
    format!("{{{}}}", parts.join(","))
}

fn escape_json_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 8);
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn cmd_score(args: &[String]) -> i32 {
    let mut g6 = String::new();
    let mut cap = 64u32;
    let mut node_budget = 50_000u32;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--graph6" => {
                i += 1;
                g6 = args.get(i).cloned().unwrap_or_default();
            }
            "--cap" => {
                i += 1;
                cap = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(64);
            }
            "--node-budget" => {
                i += 1;
                node_budget = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(50_000);
            }
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    let graph = match BitGraph::from_graph6(&g6) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("graph6 error: {e}");
            return 2;
        }
    };
    let lengths = forbidden_lengths(graph.n);
    let mut scratch = DfsScratch::new();
    let (_dom, results) = evaluate_lengths(
        &graph,
        lengths,
        cap,
        node_budget,
        None,
        false,
        &mut scratch,
        true,
    );
    let mut total = 0u32;
    let mut weighted = 0u32;
    let mut complete = true;
    let mut counts = Vec::new();
    for r in &results {
        let eff = if !r.complete { cap } else { r.count.min(cap) };
        total += eff;
        weighted += eff * (64u32 / (r.length as u32)).max(1);
        complete = complete && r.complete && r.count <= cap;
        counts.push((r.length, eff));
    }
    println!(
        "{{\"order\":{},\"size\":{},\"total\":{},\"weighted_penalty\":{},\"complete\":{},\"witness_counts\":{}}}",
        graph.n,
        graph.size(),
        total,
        weighted,
        complete,
        format_counts_json(&counts)
    );
    0
}

fn cmd_bench_score(args: &[String]) -> i32 {
    let mut orders = vec![32usize, 50, 52, 54, 56, 58, 60, 62, 64];
    let mut count = 300usize;
    let mut cap = 64u32;
    let mut mode = GraphMode::CubicFirst;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--orders" => {
                i += 1;
                if let Some(s) = args.get(i) {
                    orders = s.split(',').filter_map(|p| p.trim().parse().ok()).collect();
                }
            }
            "--count" => {
                i += 1;
                count = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(300);
            }
            "--cap" => {
                i += 1;
                cap = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(64);
            }
            "--mode" => {
                i += 1;
                if let Some(s) = args.get(i) {
                    mode = GraphMode::parse(s).unwrap_or(GraphMode::CubicFirst);
                }
            }
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    let node_budget = SearchParams::default_node_budget(cap);
    let mut scratch = DfsScratch::new();
    let mut edges_buf = Vec::new();
    let mut wc = WitnessCache::new();
    println!(
        "=== Rust direct scorer benchmark (mode={}, count={}, cap={}, node_budget={}) ===",
        mode.as_str(),
        count,
        cap,
        node_budget
    );
    for n in orders {
        let mut rng = Rng::new(20261126u64 + (n as u64) * 1009);
        let mut graphs = Vec::with_capacity(count);
        let mut g = match generate_seed(&mut rng, n, mode) {
            Ok(g) => g,
            Err(e) => {
                eprintln!("seed error for n={n}: {e}");
                return 2;
            }
        };
        for idx in 0..count {
            if idx % 25 == 0 {
                g = generate_seed(&mut rng, n, mode).unwrap();
            } else {
                g.collect_edges(&mut edges_buf);
                let (next_g, _) = mutate(&g, &edges_buf, &mut rng, mode, false, &mut wc, &mut scratch);
                g = next_g;
            }
            graphs.push(g);
        }
        for g in graphs.iter().take(10) {
            let _ = score_graph_fast(g, cap, node_budget, None, &mut scratch);
        }
        let mut samples_us = Vec::with_capacity(count);
        let t0 = Instant::now();
        for g in &graphs {
            let ts = Instant::now();
            let _ = score_graph_fast(g, cap, node_budget, None, &mut scratch);
            samples_us.push(ts.elapsed().as_nanos() as f64 / 1_000.0);
        }
        let elapsed = t0.elapsed().as_secs_f64();
        samples_us.sort_by(|a, b| a.total_cmp(b));
        let p50 = samples_us[samples_us.len() / 2];
        let p95 = samples_us[(samples_us.len() * 95 / 100).min(samples_us.len() - 1)];
        println!(
            "  n={n:2} | {:9.1} ev/s | p50={:6.1}us p95={:6.1}us",
            (count as f64) / elapsed,
            p50,
            p95
        );
    }
    0
}

fn cmd_search(args: &[String]) -> i32 {
    let mut order = 50usize;
    let mut mode = GraphMode::CubicFirst;
    let mut seed_style = SeedStyle::Random;
    let mut objective = ObjectiveMode::Total;
    let mut algorithm = Algorithm::IteratedLocalSearchTabu;
    let mut evals = 4_000usize;
    let mut workers = 1usize;
    let mut cap = 64u32;
    let mut adaptive_cap_max = 0u32;
    let mut node_budget: Option<u32> = None;
    let mut seed = 20261126u64;
    let mut targeted_prob = 0.5f64;
    let mut three_edge_prob = 0.0f64;
    let mut hashimoto_guide = false;
    let mut lns_interval = 0usize;
    let mut tabu_tenure = 64usize;
    let mut perturbation_interval = 200usize;
    let mut temperature = 8.0f64;
    let mut cooling = 0.9995f64;
    let mut restart_threshold = 50_000usize;
    let mut initial_graph6: Option<String> = None;
    let mut max_wall_seconds: Option<f64> = None;
    let mut json_output = false;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--order" => {
                i += 1;
                order = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(50);
            }
            "--mode" => {
                i += 1;
                mode = match args.get(i).map(|s| GraphMode::parse(s)) {
                    Some(Ok(m)) => m,
                    Some(Err(e)) => {
                        eprintln!("{e}");
                        return 2;
                    }
                    None => {
                        eprintln!("missing value for --mode");
                        return 2;
                    }
                };
            }
            "--seed-style" => {
                i += 1;
                seed_style = match args.get(i).map(|s| SeedStyle::parse(s)) {
                    Some(Ok(st)) => st,
                    Some(Err(e)) => {
                        eprintln!("{e}");
                        return 2;
                    }
                    None => {
                        eprintln!("missing value for --seed-style");
                        return 2;
                    }
                };
            }
            "--adaptive-cap-max" => {
                i += 1;
                adaptive_cap_max = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
            }
            "--objective" => {
                i += 1;
                objective = match args.get(i).map(|s| ObjectiveMode::parse(s)) {
                    Some(Ok(o)) => o,
                    Some(Err(e)) => {
                        eprintln!("{e}");
                        return 2;
                    }
                    None => {
                        eprintln!("missing value for --objective");
                        return 2;
                    }
                };
            }
            "--three-edge-prob" => {
                i += 1;
                three_edge_prob = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(0.0);
            }
            "--hashimoto-guide" => {
                hashimoto_guide = true;
            }
            "--lns-interval" => {
                i += 1;
                lns_interval = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
            }
            "--algorithm" => {
                i += 1;
                algorithm = args
                    .get(i)
                    .and_then(|s| Algorithm::parse(s).ok())
                    .unwrap_or(Algorithm::IteratedLocalSearchTabu);
            }
            "--evals" => {
                i += 1;
                evals = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(4_000);
            }
            "--workers" => {
                i += 1;
                workers = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(1);
            }
            "--cap" => {
                i += 1;
                cap = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(64);
            }
            "--node-budget" => {
                i += 1;
                node_budget = args.get(i).and_then(|s| s.parse().ok());
            }
            "--seed" => {
                i += 1;
                seed = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(20261126);
            }
            "--targeted-prob" => {
                i += 1;
                targeted_prob = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(0.5);
            }
            "--tabu-tenure" => {
                i += 1;
                tabu_tenure = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(64);
            }
            "--perturbation-interval" => {
                i += 1;
                perturbation_interval = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(200);
            }
            "--temperature" => {
                i += 1;
                temperature = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(8.0);
            }
            "--cooling" => {
                i += 1;
                cooling = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(0.9995);
            }
            "--restart-threshold" => {
                i += 1;
                restart_threshold = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(50_000);
            }
            "--initial-graph6" => {
                i += 1;
                initial_graph6 = args.get(i).cloned();
            }
            "--wall-seconds" => {
                i += 1;
                max_wall_seconds = args.get(i).and_then(|s| s.parse().ok());
            }
            "--json" => {
                json_output = true;
            }
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }

    let initial_graph = match initial_graph6 {
        Some(ref g6) => match BitGraph::from_graph6(g6) {
            Ok(g) => {
                order = g.n;
                Some(g)
            }
            Err(e) => {
                eprintln!("initial graph6 error: {e}");
                return 2;
            }
        },
        None => None,
    };

    let params = SearchParams {
        order,
        mode,
        seed_style,
        objective,
        algorithm,
        evaluations_per_worker: evals,
        witness_cap: cap,
        adaptive_cap_max,
        node_budget: node_budget.unwrap_or_else(|| SearchParams::default_node_budget(cap)),
        targeted_prob,
        three_edge_prob,
        hashimoto_guide,
        lns_interval,
        temperature,
        cooling,
        restart_threshold,
        tabu_tenure,
        perturbation_interval,
        initial_graph,
        max_wall_seconds,
    };

    let (lanes, wall_s) = match run_parallel(&params, workers, seed) {
        Ok(res) => res,
        Err(e) => {
            eprintln!("search error: {e}");
            return 2;
        }
    };

    let total_evals: usize = lanes.iter().map(|l| l.evaluated).sum();
    let total_cutoffs: usize = lanes.iter().map(|l| l.cutoffs).sum();
    let total_accepted: usize = lanes.iter().map(|l| l.accepted).sum();
    let total_improvements: usize = lanes.iter().map(|l| l.improvements).sum();
    let best = lanes
        .iter()
        .min_by_key(|l| l.best_score.ordering_key_for(objective))
        .expect("at least one lane");
    let last_lane = lanes.last().expect("at least one lane");
    let agg_sps = (total_evals as f64) / wall_s.max(1e-9);
    let best_g6 = escape_json_str(&best.best_graph.to_graph6());
    let final_g6 = escape_json_str(&last_lane.final_graph.to_graph6());

    if json_output {
        println!(
            "{{\"engine\":\"rust\",\"order\":{},\"mode\":\"{}\",\"seed_style\":\"{}\",\"objective\":\"{}\",\"algorithm\":\"{}\",\"workers\":{},\"effective_cap\":{},\"total_evaluations\":{},\"wall_seconds\":{:.6},\"evals_per_second\":{:.2},\"accepted\":{},\"improvements\":{},\"cutoffs\":{},\"best_total\":{},\"best_weighted_penalty\":{},\"best_complete\":{},\"best_witness_counts\":{},\"best_graph6\":\"{}\",\"final_total\":{},\"final_weighted_penalty\":{},\"final_complete\":{},\"final_witness_counts\":{},\"final_graph6\":\"{}\"}}",
            order,
            mode.as_str(),
            seed_style.as_str(),
            objective.as_str(),
            algorithm.as_str(),
            workers,
            best.effective_cap,
            total_evals,
            wall_s,
            agg_sps,
            total_accepted,
            total_improvements,
            total_cutoffs,
            best.best_score.total,
            best.best_score.weighted_penalty,
            best.best_score.complete,
            format_counts_json(best.best_score.counts_slice()),
            best_g6,
            last_lane.final_score.total,
            last_lane.final_score.weighted_penalty,
            last_lane.final_score.complete,
            format_counts_json(last_lane.final_score.counts_slice()),
            final_g6
        );
    } else {
        println!(
            "rust | n={} alg={} seed={} cap={} workers={} | {} ev in {:.3}s | {:.1} ev/s | cutoffs={} | best={} (weighted={}, cmp={})",
            order,
            algorithm.as_str(),
            seed_style.as_str(),
            best.effective_cap,
            workers,
            total_evals,
            wall_s,
            agg_sps,
            total_cutoffs,
            format_counts_json(best.best_score.counts_slice()),
            best.best_score.weighted_penalty,
            best.best_score.complete
        );
    }
    0
}

fn cmd_verify_exact(args: &[String]) -> i32 {
    let mut g6 = String::new();
    let mut max_width = 14usize;
    let mut max_states = 2_000_000usize;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--graph6" => {
                i += 1;
                g6 = args.get(i).cloned().unwrap_or_default();
            }
            "--max-width" => {
                i += 1;
                max_width = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(14);
            }
            "--max-states" => {
                i += 1;
                max_states = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(2_000_000);
            }
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    let graph = match BitGraph::from_graph6(&g6) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("graph6 error: {e}");
            return 2;
        }
    };
    let t0 = Instant::now();
    let mut scratch = DfsScratch::new();
    let lengths = forbidden_lengths(graph.n);

    // 1) Exact fast checks for C4, C8, C16 (analytic + Bitset MitM)
    let mut status_map: Vec<(u16, &'static str)> = Vec::new();
    let mut bnr_nodes = 0u64;
    let mut c16_exact_count: Option<u32> = None;

    if graph.n <= 64 {
        let g64 = crate::graph::BitGraph64::from_graph(&graph);
        for &len in lengths {
            match len {
                4 | 8 => {
                    let r = crate::cycles::count_cycles_fast_u64(&g64, len, 1, 0, 0, &mut scratch);
                    status_map.push((len, if r.count > 0 { "FOUND" } else { "ABSENT" }));
                }
                16 => {
                    if let Some(r) = crate::cycles::count_c16_mitm_u64(
                        &g64.rows,
                        g64.n,
                        u32::MAX,
                        0,
                        &mut scratch,
                    ) {
                        c16_exact_count = Some(r.count);
                        status_map.push((16, if r.count > 0 { "FOUND" } else { "ABSENT" }));
                    } else {
                        status_map.push((16, "PENDING"));
                    }
                }
                _ if (len as usize) == g64.n => {
                    // Forced-Edge Branch-and-Reduce for exact Hamiltonian cycle C_n
                    match crate::exact_verify::exact_cubic_hamiltonian_bnr_u64(&g64.rows, g64.n, 0)
                    {
                        crate::exact_verify::BnrResult::Found { nodes, .. } => {
                            bnr_nodes = nodes;
                            status_map.push((len, "FOUND"));
                        }
                        crate::exact_verify::BnrResult::Absent { nodes } => {
                            bnr_nodes = nodes;
                            status_map.push((len, "ABSENT"));
                        }
                        crate::exact_verify::BnrResult::BudgetExceeded { nodes } => {
                            bnr_nodes = nodes;
                            status_map.push((len, "PENDING"));
                        }
                    }
                }
                _ => {
                    status_map.push((len, "PENDING"));
                }
            }
        }
    } else {
        for &len in lengths {
            if len == 16 {
                if let Some(r) = crate::cycles::count_c16_mitm_u128(
                    &graph.rows,
                    graph.n,
                    u32::MAX,
                    0,
                    &mut scratch,
                ) {
                    c16_exact_count = Some(r.count);
                    status_map.push((16, if r.count > 0 { "FOUND" } else { "ABSENT" }));
                    continue;
                }
            }
            status_map.push((len, "PENDING"));
        }
    }

    // 2) Single-pass Frontier DP for remaining lengths (e.g. C32, C64 when n > 64)
    let mut fdp_status = "SKIPPED";
    let mut fdp_max_frontier = 0usize;
    let mut fdp_peak_states = 0usize;
    let mut fdp_ms = 0.0f64;
    if status_map.iter().any(|&(_, st)| st == "PENDING") {
        match crate::exact_verify::exact_spectrum_frontier_dp(&graph, max_width, max_states) {
            crate::exact_verify::FrontierDpResult::Complete {
                spectrum,
                max_frontier,
                peak_states,
                elapsed_ms,
            } => {
                fdp_status = "COMPLETE";
                fdp_max_frontier = max_frontier;
                fdp_peak_states = peak_states;
                fdp_ms = elapsed_ms;
                for item in &mut status_map {
                    if item.1 == "PENDING" && (item.0 as usize) < 128 {
                        let has = (spectrum & (1u128 << (item.0 as usize))) != 0;
                        item.1 = if has { "FOUND" } else { "ABSENT" };
                    }
                }
            }
            crate::exact_verify::FrontierDpResult::TooWide {
                max_frontier,
                peak_states,
                elapsed_ms,
            } => {
                fdp_status = "TOO_WIDE";
                fdp_max_frontier = max_frontier;
                fdp_peak_states = peak_states;
                fdp_ms = elapsed_ms;
            }
        }
    }

    let elapsed_ms = t0.elapsed().as_secs_f64() * 1000.0;
    let status_json: Vec<String> = status_map
        .iter()
        .map(|(l, st)| format!("\"{l}\":\"{st}\""))
        .collect();
    let c16_json = match c16_exact_count {
        Some(c) => c.to_string(),
        None => "null".to_string(),
    };
    println!(
        "{{\"order\":{},\"size\":{},\"elapsed_ms\":{:.3},\"c16_exact_count\":{},\"bnr_nodes\":{},\"frontier_dp_status\":\"{}\",\"frontier_dp_max_width\":{},\"frontier_dp_peak_states\":{},\"frontier_dp_ms\":{:.3},\"lengths\":{{{}}}}}",
        graph.n,
        graph.size(),
        elapsed_ms,
        c16_json,
        bnr_nodes,
        fdp_status,
        fdp_max_frontier,
        fdp_peak_states,
        fdp_ms,
        status_json.join(",")
    );
    0
}

fn cmd_lns_polish(args: &[String]) -> i32 {
    let mut g6 = String::new();
    let mut mode = GraphMode::CubicFirst;
    let mut k_min = 4usize;
    let mut k_max = 7usize;
    let mut wall_seconds = 5.0f64;
    let mut workers = 16usize;
    let mut seed = 20261126u64;
    let mut allow_sideways = true;
    let mut node_cap = 20_000u32;
    let mut rrt_slack = 0u32;
    let mut preserve_bipartite = false;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--graph6" => {
                i += 1;
                g6 = args.get(i).cloned().unwrap_or_default();
            }
            "--mode" => {
                i += 1;
                mode = match args.get(i).map(|s| GraphMode::parse(s)) {
                    Some(Ok(m)) => m,
                    Some(Err(e)) => {
                        eprintln!("{e}");
                        return 2;
                    }
                    None => {
                        eprintln!("missing value for --mode");
                        return 2;
                    }
                };
            }
            "--k-min" => {
                i += 1;
                k_min = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(4);
            }
            "--k-max" => {
                i += 1;
                k_max = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(7);
            }
            "--wall-seconds" => {
                i += 1;
                wall_seconds = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(5.0);
            }
            "--workers" => {
                i += 1;
                workers = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(16);
            }
            "--seed" => {
                i += 1;
                seed = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(20261126);
            }
            "--node-cap" => {
                i += 1;
                node_cap = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(20_000);
            }
            "--rrt-slack" => {
                i += 1;
                rrt_slack = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
            }
            "--bipartite" => {
                preserve_bipartite = true;
            }
            "--no-sideways" => {
                allow_sideways = false;
            }
            "--json" => {}
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    let graph = match BitGraph::from_graph6(&g6) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("graph6 error: {e}");
            return 2;
        }
    };
    if graph.n > 128 {
        eprintln!("lns-polish supports n <= 128 (got {})", graph.n);
        return 2;
    }
    if graph.n > 64 {
        let summary = crate::lns::run_parallel_lns_polish_u128(
            graph,
            mode,
            k_min,
            k_max,
            wall_seconds,
            workers,
            seed,
            allow_sideways,
            node_cap,
            rrt_slack,
            preserve_bipartite,
        );
        let best_g6 = escape_json_str(&summary.best_graph.to_graph6());
        println!(
            "{{\"order\":{},\"mode\":\"{}\",\"k_min\":{},\"k_max\":{},\"workers\":{},\"rrt_slack\":{},\"bipartite\":{},\"wall_seconds\":{:.3},\"initial_c16\":{},\"best_c16\":{},\"total_steps\":{},\"total_leaves\":{},\"improvements\":{},\"sideways_moves\":{},\"best_graph6\":\"{}\"}}",
            graph.n,
            mode.as_str(),
            k_min,
            k_max,
            workers,
            rrt_slack,
            preserve_bipartite,
            summary.wall_seconds,
            summary.initial_c16,
            summary.best_c16,
            summary.total_steps,
            summary.total_leaves,
            summary.improvements,
            summary.sideways_moves,
            best_g6
        );
        return 0;
    }
    let g64 = crate::graph::BitGraph64::from_graph(&graph);
    let summary = crate::lns::run_parallel_lns_polish(
        g64,
        mode,
        k_min,
        k_max,
        wall_seconds,
        workers,
        seed,
        allow_sideways,
        node_cap,
        rrt_slack,
        preserve_bipartite,
    );
    let best_g6 = escape_json_str(&summary.best_graph.to_graph().to_graph6());
    println!(
        "{{\"order\":{},\"mode\":\"{}\",\"k_min\":{},\"k_max\":{},\"workers\":{},\"rrt_slack\":{},\"bipartite\":{},\"wall_seconds\":{:.3},\"initial_c16\":{},\"best_c16\":{},\"total_steps\":{},\"total_leaves\":{},\"improvements\":{},\"sideways_moves\":{},\"best_graph6\":\"{}\"}}",
        graph.n,
        mode.as_str(),
        k_min,
        k_max,
        workers,
        rrt_slack,
        preserve_bipartite,
        summary.wall_seconds,
        summary.initial_c16,
        summary.best_c16,
        summary.total_steps,
        summary.total_leaves,
        summary.improvements,
        summary.sideways_moves,
        best_g6
    );
    0
}

fn cmd_bjorklund_c32(args: &[String]) -> i32 {
    let mut g6 = String::new();
    let mut length = 32usize;
    let mut rounds = 2usize;
    let mut workers = 16usize;
    let mut seed = 20261126u64;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--graph6" => {
                i += 1;
                g6 = args.get(i).cloned().unwrap_or_default();
            }
            "--length" => {
                i += 1;
                length = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(32);
            }
            "--rounds" => {
                i += 1;
                rounds = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(2);
            }
            "--workers" => {
                i += 1;
                workers = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(16);
            }
            "--seed" => {
                i += 1;
                seed = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(20261126);
            }
            "--json" => {}
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    let graph = match BitGraph::from_graph6(&g6) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("graph6 error: {e}");
            return 2;
        }
    };
    match crate::voltage_bipartite::bipartite_cycle_sieve_gf2_16(
        &graph, length, rounds, workers, seed, None,
    ) {
        Ok(res) => {
            println!(
                "{{\"order\":{},\"length\":{},\"found\":{},\"rounds\":{},\"roots_tested\":{},\"elapsed_ms\":{:.3},\"pclmulqdq_enabled\":{}}}",
                graph.n,
                res.length,
                res.found,
                res.rounds,
                res.roots_tested,
                res.elapsed_ms,
                res.pclmulqdq_enabled
            );
            0
        }
        Err(e) => {
            eprintln!("bjorklund-c32 error: {e}");
            2
        }
    }
}

fn cmd_voltage_search(args: &[String]) -> i32 {
    let mut base_name = "theta4".to_string();
    let mut group_name = "f20".to_string();
    let mut steps = 50_000u64;
    let mut workers = 16usize;
    let mut seed = 20261126u64;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--base" => {
                i += 1;
                base_name = args.get(i).cloned().unwrap_or_else(|| "theta4".to_string());
            }
            "--group" => {
                i += 1;
                group_name = args.get(i).cloned().unwrap_or_else(|| "f20".to_string());
            }
            "--steps" => {
                i += 1;
                steps = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(50_000);
            }
            "--workers" => {
                i += 1;
                workers = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(16);
            }
            "--seed" => {
                i += 1;
                seed = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(20261126);
            }
            "--json" => {}
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    let base = match crate::voltage_bipartite::BipartiteCubicBase::parse(&base_name) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("{e}");
            return 2;
        }
    };
    let group = match crate::voltage_bipartite::FiniteGroup::parse(&group_name) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("{e}");
            return 2;
        }
    };
    let summary =
        crate::voltage_bipartite::run_voltage_lift_search(&base, &group, steps, workers, seed);
    let best_g6_json = match summary.best_graph6 {
        Some(ref g6) => format!("\"{}\"", escape_json_str(g6)),
        None => "null".to_string(),
    };
    let v_json: Vec<String> = summary.best_voltages.iter().map(|x| x.to_string()).collect();
    println!(
        "{{\"base\":\"{}\",\"group\":\"{}\",\"order\":{},\"evaluated_lifts\":{},\"valid_lifts\":{},\"c4_c8_zero_hits\":{},\"c4_c8_c16_zero_hits\":{},\"c32_sieve_absent_hits\":{},\"best_c4\":{},\"best_c8\":{},\"best_c16\":{},\"best_c32_flag\":{},\"best_voltages\":[{}],\"wall_seconds\":{:.3},\"best_graph6\":{}}}",
        summary.base_name,
        summary.group_name,
        summary.order,
        summary.evaluated_lifts,
        summary.valid_lifts,
        summary.c4_c8_zero_hits,
        summary.c4_c8_c16_zero_hits,
        summary.c32_sieve_absent_hits,
        summary.best_key.0,
        summary.best_key.1,
        summary.best_key.2,
        summary.best_key.3,
        v_json.join(","),
        summary.wall_seconds,
        best_g6_json
    );
    0
}

fn cmd_verify_large(args: &[String]) -> i32 {
    let mut g6 = String::new();
    let mut g6_file = String::new();
    let mut lengths = vec![4usize, 8, 16, 32];
    let mut workers = 16usize;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--graph6" => {
                i += 1;
                g6 = args.get(i).cloned().unwrap_or_default();
            }
            "--graph6-file" => {
                i += 1;
                g6_file = args.get(i).cloned().unwrap_or_default();
            }
            "--lengths" => {
                i += 1;
                let Some(s) = args.get(i) else {
                    eprintln!("missing value for --lengths");
                    return 2;
                };
                lengths.clear();
                for part in s.split(',') {
                    let trimmed = part.trim();
                    match trimmed.parse::<usize>() {
                        Ok(v) if v >= 4 && v % 2 == 0 => lengths.push(v),
                        _ => {
                            eprintln!("invalid --lengths token: '{trimmed}' (must be even integer >= 4)");
                            return 2;
                        }
                    }
                }
                if lengths.is_empty() {
                    eprintln!("--lengths cannot be empty");
                    return 2;
                }
            }
            "--workers" => {
                i += 1;
                workers = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(16);
            }
            "--json" => {}
            other => {
                eprintln!("unknown argument: {other}");
                return 2;
            }
        }
        i += 1;
    }
    if !g6_file.is_empty() {
        g6 = match std::fs::read_to_string(&g6_file) {
            Ok(s) => s.trim().to_string(),
            Err(e) => {
                eprintln!("failed to read {g6_file}: {e}");
                return 2;
            }
        };
    }
    let graph = match crate::large_verify::LargeGraph::from_graph6(&g6) {
        Ok(g) => g,
        Err(e) => {
            eprintln!("graph6 error: {e}");
            return 2;
        }
    };
    let summary = match crate::large_verify::verify_large_graph(&graph, &lengths, workers) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("verify-large error: {e}");
            return 2;
        }
    };
    let mut len_entries = Vec::new();
    let mut ms_entries = Vec::new();
    for (len, found, witness, ms) in &summary.results {
        let status = if *found { "FOUND" } else { "ABSENT" };
        len_entries.push(format!("\"{len}\":\"{status}\""));
        ms_entries.push(format!("\"{len}\":{ms:.2}"));
        let _ = witness;
    }
    println!(
        "{{\"order\":{},\"size\":{},\"min_deg\":{},\"max_deg\":{},\"biconnected\":{},\"total_ms\":{:.2},\"lengths\":{{{}}},\"elapsed_ms_by_length\":{{{}}}}}",
        summary.order,
        summary.size,
        summary.min_deg,
        summary.max_deg,
        summary.biconnected,
        summary.total_ms,
        len_entries.join(","),
        ms_entries.join(","),
    );
    0
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!(
            "usage: sglab-rust-engine --version | --serve | score | bench-score | search | verify-exact | verify-large | lns-polish | voltage-search | bjorklund-c32"
        );
        process::exit(2);
    }
    let code = match args[1].as_str() {
        "--version" => {
            println!("sglab-rust-engine 2");
            0
        }
        "--serve" => protocol::serve_protocol_v2(),
        "score" => cmd_score(&args[2..]),
        "bench-score" => cmd_bench_score(&args[2..]),
        "search" => cmd_search(&args[2..]),
        "verify-exact" => cmd_verify_exact(&args[2..]),
        "verify-large" => cmd_verify_large(&args[2..]),
        "lns-polish" => cmd_lns_polish(&args[2..]),
        "voltage-search" => cmd_voltage_search(&args[2..]),
        "bjorklund-c32" => cmd_bjorklund_c32(&args[2..]),
        other => {
            eprintln!("unknown subcommand: {other}");
            2
        }
    };
    process::exit(code);
}
