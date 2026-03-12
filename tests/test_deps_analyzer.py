"""Tests for dependency analyzer formatting helpers."""

from __future__ import annotations

import io
import zipfile

from deps_analyzer import _truncate_middle, analyze_deps_zip_bytes_report


def test_truncate_middle_keeps_short_text_unchanged():
    assert _truncate_middle("short", 10) == "short"


def test_truncate_middle_compacts_long_text_with_ellipsis():
    value = "msdyn_employeeeselfservicetemplateconfig_long_component_name"
    out = _truncate_middle(value, 20)

    assert len(out) == 20
    assert "…" in out
    assert out.startswith("msdyn_emp")
    assert out.endswith("t_name")


def test_asset_set_components_are_discovered_when_rootcomponents_are_sparse():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr(
                        "solution.xml",
                        """
<ImportExportXml>
    <SolutionManifest>
        <UniqueName>AssetOnlyDeps</UniqueName>
        <Version>1.0.0.0</Version>
        <Managed>1</Managed>
        <Publisher><UniqueName>test</UniqueName></Publisher>
        <RootComponents />
    </SolutionManifest>
</ImportExportXml>
""".strip(),
                )
                zf.writestr(
                        "Assets/botcomponent_connectionreferenceset.xml",
                        """
<botcomponent_connectionreferenceset>
    <botcomponent_connectionreference
        botcomponentid.schemaname="agent.topic.X"
        connectionreferenceid.connectionreferencelogicalname="contoso_shared_conn" />
</botcomponent_connectionreferenceset>
""".strip(),
                )
                zf.writestr(
                        "Assets/botcomponent_environmentvariabledefinitionset.xml",
                        """
<botcomponent_environmentvariabledefinitionset>
    <botcomponent_environmentvariabledefinition
        botcomponentid.schemaname="agent.topic.X"
        environmentvariabledefinitionid.schemaname="contoso_env_url" />
</botcomponent_environmentvariabledefinitionset>
""".strip(),
                )
                zf.writestr(
                        "Assets/botcomponent_workflowset.xml",
                        """
<botcomponent_workflowset>
    <botcomponent_workflow
        botcomponentid.schemaname="agent.topic.X"
        workflowid.workflowid="11111111-2222-3333-4444-555555555555" />
</botcomponent_workflowset>
""".strip(),
                )
                zf.writestr(
                        "Assets/botcomponent_msdyn_aimodelset.xml",
                        """
<botcomponent_msdyn_aimodelset>
    <botcomponent_msdyn_aimodel
        botcomponentid.schemaname="agent.topic.X"
        msdyn_aimodelid.msdyn_aimodelid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" />
</botcomponent_msdyn_aimodelset>
""".strip(),
                )

        report = analyze_deps_zip_bytes_report(buf.getvalue(), detailed_diagram=True)
        rows = report["component_rows"]
        schemas = {r["schema"] for r in rows}

        assert "contoso_shared_conn" in schemas
        assert "contoso_env_url" in schemas
        assert "11111111-2222-3333-4444-555555555555" in schemas
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in schemas

        relation_rows = report["relation_rows"]
        # Explicit Assets mappings should appear as relation rows.
        assert any(r["dependent"] == "X" and r["dependent_type"] == "Topic" for r in relation_rows)
        assert any(r["required"] == "contoso_shared_conn" and "Assets/connectionreferenceset" in r["source"] for r in relation_rows)


def test_missing_dependency_botcomponent_names_are_shortened_and_typed():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr(
                        "solution.xml",
                        """
<ImportExportXml>
    <SolutionManifest>
        <UniqueName>DepsNames</UniqueName>
        <Version>1.0.0.0</Version>
        <Managed>1</Managed>
        <Publisher><UniqueName>test</UniqueName></Publisher>
        <RootComponents />
        <MissingDependencies>
            <MissingDependency>
                <Required
                    type="botcomponent"
                    id.schemaname="msdyn_copilotforemployeeselfservicehr.topic.ConversationStart" />
                <Dependent
                    type="botcomponent"
                    id.schemaname="msdyn_copilotforemployeeselfservicehr.topic.ConversationStart" />
            </MissingDependency>
        </MissingDependencies>
    </SolutionManifest>
</ImportExportXml>
""".strip(),
                )

        report = analyze_deps_zip_bytes_report(buf.getvalue(), detailed_diagram=False)
        rows = report["relation_rows"]
        assert rows
        assert rows[0]["dependent"] == "ConversationStart"
        assert rows[0]["dependent_type"] == "Topic"
        assert rows[0]["required"] == "ConversationStart"
