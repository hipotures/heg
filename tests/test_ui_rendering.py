from __future__ import annotations

from pathlib import Path
import unittest

from sglab.comparison_web import (
    blind_page,
    comparison_detail_page,
    comparisons_page,
    cost_profiles_page,
    error_page,
    new_comparison_page,
)


class SemanticUiRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = {
            "gpt-5.6-luna": ["medium", "high", "xhigh"],
            "gpt-5.6-sol": ["medium", "high", "xhigh"],
        }
        self.fixtures = [
            {"fixture_id": "fixture-a4", "display_name": "Preserved A4"}
        ]

    def decode(self, value: bytes) -> str:
        return value.decode("utf-8")

    def test_theme_is_switchable_and_persisted_on_every_page(self) -> None:
        pages = [
            comparisons_page(),
            new_comparison_page(self.catalog, self.fixtures),
            comparison_detail_page("suite-demo"),
            blind_page("suite-demo"),
            cost_profiles_page(self.catalog),
            error_page(404, "Not found", "Missing page"),
        ]
        for body in pages:
            html = self.decode(body)
            self.assertIn("id=\"theme-toggle\"", html)
            self.assertIn("localStorage.getItem('sglab-theme')", html)
            self.assertIn("localStorage.setItem('sglab-theme'", html)
            self.assertIn(':root[data-theme="dark"]', html)

        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("id=\"theme-toggle\"", dashboard)
        self.assertIn("localStorage.getItem('sglab-theme')", dashboard)
        self.assertIn("localStorage.setItem('sglab-theme'", dashboard)
        self.assertIn(':root[data-theme="dark"]', dashboard)

    def test_action_renderers_cover_reviewed_action_types(self) -> None:
        html = self.decode(comparison_detail_page("suite-demo"))
        for action in (
            "start_lane",
            "request_diagnostic",
            "set_review_trigger",
            "promote_candidate",
            "schedule_verification",
            "stop_lane",
        ):
            self.assertIn(action, html)
        self.assertIn("Technical decision JSON", html)
        self.assertIn("Raw server decision", html)
        self.assertIn(
            "Array.isArray(parsed)?parsed:parsed?.actions",
            html,
        )
        self.assertIn(
            "actionSpaceLabels(t.applicable_action_space_json)",
            html,
        )

    def test_semantic_renderer_omits_null_values(self) -> None:
        html = self.decode(comparison_detail_page("suite-demo"))
        self.assertIn(
            "v!==null&&v!==undefined&&v!==''",
            html,
        )
        self.assertIn("semanticFields", html)

    def test_long_identifiers_are_abbreviated_with_full_title(self) -> None:
        html = self.decode(comparisons_page())
        self.assertIn("s.length>20", html)
        self.assertIn('title="${esc(v)}"', html)
        self.assertIn('aria-label="Copy full identifier"', html)
        self.assertIn("overflow-wrap:anywhere", html)

    def test_raw_json_is_secondary_to_semantic_content(self) -> None:
        html = self.decode(comparison_detail_page("suite-demo"))
        self.assertIn("<details>", html)
        self.assertIn("Measured downstream effect", html)
        self.assertNotIn('<pre id="preflight">', html)
        self.assertNotIn("<th>Decision</th>", html)

    def test_responsive_and_accessible_form_contracts_are_present(self) -> None:
        html = self.decode(new_comparison_page(self.catalog, self.fixtures))
        self.assertIn("@media(max-width:700px)", html)
        self.assertIn("<fieldset>", html)
        self.assertIn("<legend>", html)
        self.assertIn("Hard maximum inference starts", html)
        self.assertIn("Measurement only", html)

    def test_empty_and_error_states_are_explicit(self) -> None:
        list_html = self.decode(comparisons_page())
        self.assertIn("No comparison suites match these filters.", list_html)
        error_html = self.decode(
            error_page(404, "Comparison not found", "No suite exists.")
        )
        self.assertIn("HTTP 404", error_html)
        self.assertIn("Return to dashboard", error_html)

    def test_blind_page_uses_semantic_decisions_and_hides_contract(self) -> None:
        html = self.decode(blind_page("suite-demo"))
        self.assertIn("decisionCard(pair[0].normalized_decision_json", html)
        self.assertIn("remain hidden until submission", html)
        self.assertIn('id="blind-empty" class="empty-state" hidden', html)
        self.assertIn(
            "Failed or invalid turns remain available in the suite reliability view",
            html,
        )
        self.assertNotIn('<pre id="a"', html)

    def test_cost_profiles_have_semantic_history_cards(self) -> None:
        html = self.decode(cost_profiles_page(self.catalog))
        self.assertIn("profileCard", html)
        self.assertIn("Relative multiplier", html)
        self.assertIn("API-equivalent", html)
        self.assertIn("maximumFractionDigits:4", html)
        self.assertNotIn('<pre id="profiles"', html)

    def test_dashboard_bounds_primary_lists_and_keeps_raw_details(self) -> None:
        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("boundedList('actions'", dashboard)
        self.assertIn("boundedList('candidates-list'", dashboard)
        self.assertIn("/api/candidates?limit=24", dashboard)
        self.assertIn("Raw action record", dashboard)
        self.assertIn("Candidate metadata", dashboard)
        self.assertIn("Show Director request and answer", dashboard)
        self.assertIn("What the Director received", dashboard)
        self.assertIn("What the Director answered", dashboard)
        self.assertIn("Response pending", dashboard)
        self.assertIn("Technical payload (raw JSON)", dashboard)
        self.assertIn("expandedTurnCommunication", dashboard)
        self.assertIn("turnCommunicationCache", dashboard)
        self.assertIn("expandedDetails", dashboard)
        self.assertIn("data-persist-details", dashboard)
        self.assertIn("lane:${l.lane_id}:controls", dashboard)
        self.assertIn("viewAnchor", dashboard)
        self.assertIn("detailScrollPositions", dashboard)
        self.assertIn("refreshDetailsSelector", dashboard)
        self.assertIn("pre.scrollTop=position.top", dashboard)
        self.assertIn("pre.scrollLeft=position.left", dashboard)
        self.assertIn("captureRefreshView()", dashboard)
        self.assertIn("restoreRefreshView(viewAnchor)", dashboard)
        self.assertIn("window.scrollBy", dashboard)
        self.assertIn("const selectionIntersects=element=>", dashboard)
        self.assertIn("replaceHtmlPreservingSelection", dashboard)
        self.assertIn("badge,selectionIntersects", dashboard)
        self.assertIn("document.getElementById('comparisons-overview').hidden=!last", dashboard)
        self.assertIn("document.querySelector('[data-comparisons-nav]').hidden=!last", dashboard)
        self.assertIn("document.querySelector('[data-visuals-nav]').hidden=!campaignMode", dashboard)
        for anchor, text in (
            ("#comparisons-overview", "Comparisons"),
            ("#campaign", "Campaign"),
            ("#campaign-status", "Status"),
            ("#visuals", "Visuals"),
            ("#attempts-section", "Attempts"),
            ("#memory-section", "Memory"),
            ("#assessment-section", "Assessment"),
            ("#decisions", "Decisions"),
            ("#lanes", "Lanes"),
            ("#revisions-section", "Revisions"),
            ("#turns-section", "Turns"),
            ("#candidates", "Candidates"),
            ("#events", "Events"),
            ("#telemetry-section", "Telemetry"),
            ("#runs-section", "Runs"),
        ):
            self.assertIn(f'<a href="{anchor}"', dashboard)
            self.assertIn(f">{text}</a>", dashboard)
        self.assertIn("data-legacy-run", dashboard)
        self.assertIn("section.hidden=campaignMode", dashboard)
        self.assertIn("Campaign candidates", dashboard)
        self.assertIn("campaign.candidates||[]", dashboard)
        self.assertIn("Campaign stopped fail-closed", dashboard)
        self.assertIn(
            "const currentFault=campaign.state==='paused_fault'"
            "||campaign.state==='infrastructure_failure'",
            dashboard,
        )
        self.assertIn("['Current fault',currentFault?", dashboard)
        self.assertIn("campaign.fault_detail", dashboard)
        self.assertIn("resume-campaign", dashboard)
        self.assertIn("campaign.resume_supported", dashboard)
        self.assertIn("/api/research-campaign/resume-preview", dashboard)
        self.assertIn("/api/research-campaign/resume", dashboard)
        self.assertIn("Execution attempts", dashboard)
        self.assertIn("Scientific memory", dashboard)
        self.assertIn("function metricTile(", dashboard)
        self.assertIn("function copyDashboardTarget(target)", dashboard)
        self.assertIn('class="metric copyable-tile', dashboard)
        self.assertIn("data-copy-text", dashboard)
        self.assertIn("campaign.campaign_id||'—'", dashboard)
        self.assertIn("attempt.code_commit", dashboard)
        self.assertIn("Newest first · local time", dashboard)
        self.assertIn("new Intl.DateTimeFormat", dashboard)
        self.assertIn("new Intl.DateTimeFormat('pl-PL'", dashboard)
        self.assertIn("hourCycle:'h23'", dashboard)
        self.assertIn("Started locally · ${localTimeHtml(started)}", dashboard)
        self.assertIn("localTimeRangeHtml(attempt.started_at", dashboard)
        self.assertIn("localTimeHtml(event.timestamp", dashboard)
        self.assertIn("localTimeHtml(h.created_at)", dashboard)
        self.assertIn("localTimeHtml(r.applied_at)", dashboard)
        self.assertIn("localTimeHtml(r.created_at)", dashboard)
        self.assertIn("'Stored UTC':'Stored timestamp'", dashboard)
        self.assertIn(
            "${esc(row.model)}:${esc(row.reasoning_effort)}",
            dashboard,
        )
        self.assertIn(
            'title="Requested model and reasoning effort"',
            dashboard,
        )
        comparison = self.decode(comparisons_page())
        self.assertIn("new Intl.DateTimeFormat('pl-PL'", comparison)
        self.assertIn("hourCycle:'h23'", comparison)
        self.assertIn("created ${localTimeHtml(s.created_at)}", comparison)
        self.assertNotIn("Copy ID", dashboard)
        self.assertNotIn("copyButton", dashboard)
        self.assertNotIn('data-campaign-action="RESUME"', dashboard)
        self.assertIn("Math.min(limit,3)", dashboard)
        self.assertIn("function eventLine(line)", dashboard)
        self.assertIn("boundedList('logs',logs.lines||[],eventLine)", dashboard)
        self.assertNotIn("['Parameters', r => esc(JSON.stringify", dashboard)
        self.assertNotIn(
            "typeof v==='object'?esc(JSON.stringify(v))",
            dashboard,
        )

    def test_mobile_controls_use_touch_sized_targets(self) -> None:
        comparison = self.decode(comparisons_page())
        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "input,select,button,.copy-id,.section-heading>a,.form-actions>a"
            "{min-height:2.75rem}",
            comparison,
        )
        self.assertIn(
            "input,select,button,.section-heading>a,.form-actions>a"
            "{min-height:2.75rem}",
            dashboard,
        )
        for html in (comparison, dashboard):
            self.assertIn(
                ".section-heading>a,.form-actions>a"
                "{display:inline-flex;align-items:center}",
                html,
            )
            self.assertIn(
                ".brand strong a{display:inline-flex;align-items:center;"
                "min-height:2.75rem}",
                html,
            )

    def test_global_navigation_is_consistent_and_theme_label_does_not_wrap(self) -> None:
        comparison = self.decode(comparisons_page())
        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        expected = (
            '<a href="/">Dashboard</a><a href="/comparisons">Comparisons</a>'
            '<a href="/comparisons/new">New suite</a>'
            '<a href="/model-cost-profiles">Cost profiles</a>'
        )
        self.assertIn(expected, comparison)
        self.assertIn(expected, dashboard)
        self.assertIn("white-space:nowrap", comparison)
        self.assertIn("white-space:nowrap", dashboard)
        self.assertIn('aria-label="Dashboard sections"', dashboard)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", comparison)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", dashboard)

    def test_nested_action_parameters_are_semantic_and_wrapping_safe(self) -> None:
        comparison = self.decode(comparison_detail_page("suite-demo"))
        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        for html in (comparison, dashboard):
            self.assertIn('class="nested-object"', html)
            self.assertIn("overflow-wrap:anywhere", html)
        self.assertIn("value.some", dashboard)
        self.assertIn("value.some", comparison)
        self.assertIn("Degree ${degree}: ${count}", dashboard)

    def test_technical_id_detection_does_not_treat_invalid_as_an_id(self) -> None:
        comparison = self.decode(comparisons_page())
        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        for html in (comparison, dashboard):
            self.assertIn(r"(^|[\s_-])(id|ids|hash", html)
            self.assertNotIn(
                r"/(id|hash|sha-?256|fingerprint|prompt|director state|output schema)/i",
                html,
            )

    def test_terminal_suite_controls_use_explicit_element_lookup(self) -> None:
        html = self.decode(comparison_detail_page("suite-demo"))
        self.assertIn("document.getElementById('stop').onclick", html)
        self.assertIn("stop=document.getElementById('stop')", html)
        self.assertNotIn("stop.onclick=", html)

    def test_missing_effect_values_do_not_render_null(self) -> None:
        html = self.decode(comparison_detail_page("suite-demo"))
        self.assertIn("v==='null'", html)
        self.assertIn("scoreMissing?'Unavailable'", html)

    def test_hidden_attribute_wins_over_layout_display(self) -> None:
        html = self.decode(comparison_detail_page("suite-demo"))
        self.assertIn("[hidden]{display:none!important}", html)


if __name__ == "__main__":
    unittest.main()
