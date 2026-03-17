from __future__ import annotations

import io
import json
import zipfile

from evals_manager import analyze_evals_zip_bytes, export_solution_with_evals, preview_generated_evals
from visualizer import get_evals_data


def _solution_zip_bytes(include_existing_evals: bool) -> bytes:
    config = {
        "channels": [{"channelId": "msteams"}],
        "recognizer": {"$kind": "Microsoft.GenerativeAIRecognizer"},
        "aISettings": {"useModelKnowledge": False, "contentModeration": "Medium"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "solution.xml",
            """
<ImportExportXml>
  <SolutionManifest>
    <UniqueName>DemoLegal</UniqueName>
    <LocalizedNames>
      <LocalizedName languagecode=\"1033\" description=\"Demo Legal\" />
    </LocalizedNames>
    <Version>1.0.0.0</Version>
    <Managed>0</Managed>
  </SolutionManifest>
</ImportExportXml>
""".strip(),
        )
        zf.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\" />")
        zf.writestr("bots/copilots_demo_legal/configuration.json", json.dumps(config))
        zf.writestr("bots/copilots_demo_legal/bot.xml", "<bot><name>Demo Legal</name></bot>")
        zf.writestr(
            "botcomponents/copilots_demo_legal.gpt.default/botcomponent.xml",
            """
<botcomponent schemaname=\"copilots_demo_legal.gpt.default\">
  <name>Demo Legal</name>
  <description>Internal legal guidance bot</description>
</botcomponent>
""".strip(),
        )
        zf.writestr(
            "botcomponents/copilots_demo_legal.gpt.default/data",
            """
kind: GptComponentMetadata
displayName: Demo Legal
instructions: |-
  Answer exclusively from grounded documents.
  If the question is unclear, ask one clarifying question.
  Cite the source documents you used.
  Do not provide confidential or unavailable information.
aISettings:
  model:
    modelNameHint: GPT5Chat
""".strip(),
        )
        zf.writestr(
            "botcomponents/copilots_demo_legal.topic.Search/botcomponent.xml",
            """
<botcomponent schemaname=\"copilots_demo_legal.topic.Search\">
  <name>Search</name>
  <description>Answer policy questions</description>
  <statecode>0</statecode>
</botcomponent>
""".strip(),
        )
        zf.writestr(
            "botcomponents/copilots_demo_legal.topic.Search/data",
            """
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  triggerQueries:
    - leave policy
    - annual leave rules
  actions:
    - kind: SearchAndSummarizeContent
      knowledgeSources:
        kind: SearchSpecificKnowledgeSources
        knowledgeSources:
          - copilots_demo_legal.topic.LeavePolicyDoc
""".strip(),
        )
        zf.writestr(
            "botcomponents/copilots_demo_legal.topic.OnError/botcomponent.xml",
            """
<botcomponent schemaname=\"copilots_demo_legal.topic.OnError\">
  <name>On Error</name>
  <description>Recover gracefully</description>
  <statecode>0</statecode>
</botcomponent>
""".strip(),
        )
        zf.writestr(
            "botcomponents/copilots_demo_legal.topic.OnError/data",
            """
kind: AdaptiveDialog
beginDialog:
  kind: OnError
  actions:
    - kind: SendActivity
      activity: Sorry, something went wrong.
""".strip(),
        )

        if include_existing_evals:
            zf.writestr(
                "botcomponents/mspva_parent_tests/botcomponent.xml",
                """
<botcomponent schemaname=\"mspva_parent_tests\">
  <category>Testing</category>
  <componenttype>19</componenttype>
  <description>Existing tests</description>
  <iscustomizable>0</iscustomizable>
  <name>Existing tests</name>
  <parentbotid>
    <schemaname>copilots_demo_legal</schemaname>
  </parentbotid>
  <statecode>0</statecode>
  <statuscode>1</statuscode>
</botcomponent>
""".strip(),
            )
            zf.writestr("botcomponents/mspva_parent_tests/data", "kind: TestSetDefinition\n")
            zf.writestr(
                "botcomponents/mspva_child_test/botcomponent.xml",
                """
<botcomponent schemaname=\"mspva_child_test\">
  <category>Testing</category>
  <componenttype>19</componenttype>
  <description>mspva_child_test</description>
  <iscustomizable>0</iscustomizable>
  <name>mspva_child_test</name>
  <parentbotcomponentid>
    <schemaname>mspva_parent_tests</schemaname>
  </parentbotcomponentid>
  <parentbotid>
    <schemaname>copilots_demo_legal</schemaname>
  </parentbotid>
  <statecode>0</statecode>
  <statuscode>1</statuscode>
</botcomponent>
""".strip(),
            )
            zf.writestr(
                "botcomponents/mspva_child_test/data",
                """
kind: TestCaseDefinition
transcriptDefinition:
  testActivities:
    - kind: SendUserActivity
      originType: Imported
      activity: What is the leave policy?
      activityAssertions:
        - kind: IntentMatchAssertion
          expectedResponse: Use the grounded leave policy guidance.
          scoreThreshold: 70
""".strip(),
            )
    return buf.getvalue()


def test_analyze_evals_reports_fit_and_improve_signal():
    report = analyze_evals_zip_bytes(_solution_zip_bytes(include_existing_evals=True))

    assert report["has_existing_evals"] is True
    assert report["fit_dimensions"]
    assert 0 <= report["score"] <= 100
    assert report["should_offer_improve"] is True


def test_preview_generated_evals_returns_20_to_50_samples():
    preview = preview_generated_evals(_solution_zip_bytes(include_existing_evals=False), mode="generate", target_count=24)

    assert preview["mode"] == "generate"
    assert 20 <= len(preview["test_cases"]) <= 50
    assert len(preview["test_cases"]) == len(preview["eval_rows"])
    assert preview["category_counts"]


def test_export_solution_with_evals_injects_parseable_eval_assets():
    exported_bytes, preview = export_solution_with_evals(
        _solution_zip_bytes(include_existing_evals=False),
        mode="generate",
        target_count=24,
    )

    evals = get_evals_data(exported_bytes)

    assert preview["test_cases"]
    assert evals["test_sets"]
    assert evals["eval_sets"]
    assert sum(len(item["test_cases"]) for item in evals["test_sets"]) >= 20
    assert sum(len(item["rows"]) for item in evals["eval_sets"]) >= 20