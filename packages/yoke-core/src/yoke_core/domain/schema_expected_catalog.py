"""The table/column surface this build reads, as one declared catalog.

Dumped from a converged authoritative database: machine-generated reference
data rather than authored logic, so regenerate it from a converged universe
rather than editing it by hand, the same way Platform maintains its own
catalog fixture.

Two readers depend on it, and they ask opposite questions. The schema-drift
health check asks whether the database carries anything this build does not
know about. The serving-surface probe in
:mod:`yoke_core.domain.schema_readiness` asks the reverse — whether everything
this build reads is still there — which is what a build stranded behind a
destructive migration needs and cannot learn from any declared version floor.
Because a build ships the catalog it was written against, that catalog is a
faithful statement of what its code expects, and the probe compares it against
the live database rather than trusting a constant an author hand-wrote.

The declaration is one ``"|"``-separated string so per-table sections stay
legible in a diff. Each section is ``<table>:<col>/<TYPE>,...``. The parser is
a thin split routine with no schema-loading logic (no PRAGMA, no connection),
so it stays cheap to import and easy to unit-test against a fixed string.

Both readers compare names; the serving probe also requires native TIMESTAMPTZ
for instant fields. Other concrete types describe the schema in diagnostics.
"""

from __future__ import annotations

from typing import Dict


_EXPECTED_SCHEMA_STR = (
    "actor_external_identities:id/INTEGER,actor_id/INTEGER,issuer/TEXT,subject/TEXT,email/TEXT,linked_at/TIMESTAMPTZ,created_by_actor_id/INTEGER"
    "|actor_invites:id/INTEGER,email/TEXT,org_id/INTEGER,role_id/INTEGER,actor_id/INTEGER,status/TEXT,invited_by_actor_id/INTEGER,created_at/TIMESTAMPTZ,accepted_at/TIMESTAMPTZ,accepted_by_actor_id/INTEGER"
    "|actor_message_recipients:message_id/TEXT,recipient_kind/TEXT,actor_id/INTEGER,state/TEXT,created_at/TIMESTAMPTZ,read_at/TIMESTAMPTZ,expired_at/TIMESTAMPTZ,steering_scope/TEXT,sender_item_id/INTEGER,project_id/INTEGER,seat_session_id/TEXT,seat_claim_id/INTEGER,delivered_at/TIMESTAMPTZ,acknowledged_at/TIMESTAMPTZ"
    "|actor_org_roles:actor_id/INTEGER,org_id/INTEGER,role_id/INTEGER,granted_at/TIMESTAMPTZ,granted_by_actor_id/INTEGER"
    "|actor_project_roles:actor_id/INTEGER,project_id/INTEGER,role_id/INTEGER,granted_at/TIMESTAMPTZ,granted_by_actor_id/INTEGER"
    "|actor_ui_preferences:id/INTEGER,actor_id/INTEGER,pref_key/TEXT,value/TEXT,updated_at/TIMESTAMPTZ"
    "|actors:id/INTEGER,kind/TEXT,system_component/TEXT,name/TEXT,status/TEXT,created_at/TIMESTAMPTZ,attribution/TEXT"
    "|api_token_audit:id/INTEGER,api_token_id/INTEGER,actor_id/INTEGER,project_id/INTEGER,event_type/TEXT,outcome/TEXT,permission_key/TEXT,diagnostic_metadata/TEXT,created_at/TIMESTAMPTZ"
    "|api_tokens:id/INTEGER,token_hash/TEXT,actor_id/INTEGER,machine_id/TEXT,name/TEXT,status/TEXT,created_at/TIMESTAMPTZ,revoked_at/TIMESTAMPTZ,expires_at/TIMESTAMPTZ,last_used_at/TIMESTAMPTZ,diagnostic_metadata/TEXT"
    "|applied_migrations:migration_name/TEXT,applied_at/TIMESTAMPTZ,applied_by/TEXT,minimum_serving_version/TEXT,content_sha256/TEXT"
    "|browser_sign_in_links:selector/TEXT,code_hash/TEXT,actor_id/INTEGER,expires_at/TIMESTAMPTZ,consumed_at/TIMESTAMPTZ"
    "|capability_secrets:id/INTEGER,project_id/INTEGER,type/TEXT,key/TEXT,value/TEXT,source/TEXT,created_at/TIMESTAMPTZ"
    "|capability_templates:id/TEXT,name/TEXT,description/TEXT,required_config/TEXT,requires/TEXT,created_at/TIMESTAMPTZ"
    "|caveat_dispositions:id/INTEGER,public_ref/TEXT,archived_item_key/TEXT,transition/TEXT,attempt/INTEGER,caveat_num/INTEGER,caveat_text/TEXT,disposition/TEXT,resolution_details/TEXT,verdict_id/INTEGER,created_at/TIMESTAMPTZ"
    "|decision_request_actor_authorities:request_id/INTEGER,actor_id/INTEGER"
    "|decision_request_decisions:id/INTEGER,request_id/INTEGER,actor_id/INTEGER,action/TEXT,note/TEXT,decided_at/TIMESTAMPTZ,decided_session_id/TEXT"
    "|decision_request_role_authorities:request_id/INTEGER,scope_kind/TEXT,scope_id/INTEGER,role_name/TEXT"
    "|decision_requests:id/INTEGER,kind/TEXT,subject_type/TEXT,subject_key/TEXT,subject_context/TEXT,project_id/INTEGER,org_id/INTEGER,originator_actor_id/INTEGER,approval_mode/TEXT,status/TEXT,resolution_action/TEXT,resolution_actor_id/INTEGER,resolution_note/TEXT,resolved_at/TIMESTAMPTZ,withdrawal_reason/TEXT,withdrawn_at/TIMESTAMPTZ,consumed_at/TIMESTAMPTZ,consumed_from_stage/TEXT,consumed_to_stage/TEXT,consumed_workflow_version_id/INTEGER,created_at/TIMESTAMPTZ"
    "|deployment_flows:id/TEXT,project_id/INTEGER,name/TEXT,description/TEXT,stages/TEXT,on_failure/TEXT,created_at/TIMESTAMPTZ,status/TEXT,definition_schema_version/INTEGER,takes_delivery_custody/INTEGER,supersedes_flow_id/TEXT,target_tier/TEXT,target_environment_id/INTEGER,done_description/TEXT"
    "|deployment_preview_environments:id/INTEGER,project_id/INTEGER,env_name/TEXT,run_id/TEXT,status/TEXT,env_type/TEXT,url/TEXT,created_at/TIMESTAMPTZ"
    "|deployment_run_items:run_id/TEXT,item_id/INTEGER,added_at/TIMESTAMPTZ,delivery_intent/TEXT,requirement_selection/TEXT,requirement_snapshot/TEXT,containment_attestation/TEXT"
    "|deployment_run_qa:id/INTEGER,run_id/TEXT,check_name/TEXT,source/TEXT,blocking/INTEGER,status/TEXT,updated_at/TIMESTAMPTZ"
    "|deployment_runs:id/TEXT,project_id/INTEGER,flow/TEXT,target_tier/TEXT,target_environment_id/INTEGER,release_lineage/TEXT,status/TEXT,current_stage/TEXT,current_stage_entered_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,created_by/TEXT,carried_work/TEXT,bound_sources/TEXT,candidate_containment/TEXT,artifact_identity/TEXT,composition_resolution/TEXT,composition_frozen_at/TIMESTAMPTZ,requirement_snapshot/TEXT,driver_attachment/TEXT,settling_at/TIMESTAMPTZ,membership_removals/TEXT,create_idempotency_key/TEXT,create_request/TEXT"
    "|deployment_stage_receipts:id/INTEGER,run_id/TEXT,stage_name/TEXT,attempt_number/INTEGER,correlation_id/TEXT,target_kind/TEXT,target_name/TEXT,status/TEXT,observed_url/TEXT,observed_release_lineage/TEXT,observed_artifact_identity/TEXT,executor/TEXT,executor_receipt/TEXT,failure_reason/TEXT,created_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ"
    "|doctor_runs:id/INTEGER,ran_at/TIMESTAMPTZ,project/TEXT,scope/TEXT,runtime/TEXT,fail_count/INTEGER,pass_count/INTEGER,warn_count/INTEGER,na_count/INTEGER,results/TEXT"
    "|environments:id/INTEGER,site/INTEGER,project_id/INTEGER,name/TEXT,url/TEXT,deploy_method/TEXT,deploy_command/TEXT,health_check_url/TEXT,config_notes/TEXT,last_deployed_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,settings/TEXT"
    "|ephemeral_environments:id/INTEGER,project_id/INTEGER,branch/TEXT,item/TEXT,workflow_run_id/TEXT,github_ref/TEXT,port_api/INTEGER,port_web/INTEGER,url/TEXT,status/TEXT,started_at/TIMESTAMPTZ,stopped_at/TIMESTAMPTZ,health_check_url/TEXT,deployed_sha/TEXT,created_at/TIMESTAMPTZ"
    "|epic_dispatch_chains:id/INTEGER,epic_id/INTEGER,item_worktree_id/INTEGER,queue/TEXT,current_index/INTEGER,current_task/TEXT,current_attempt/INTEGER,max_attempts/INTEGER,no_chain/INTEGER,started_at/TIMESTAMPTZ,last_updated/TIMESTAMPTZ"
    "|epic_progress_notes:id/INTEGER,epic_id/INTEGER,task_num/INTEGER,note_num/INTEGER,body/TEXT,commit_hash/TEXT,synced_to_github/INTEGER,created_at/TIMESTAMPTZ"
    "|epic_task_files:id/INTEGER,epic_id/INTEGER,task_num/INTEGER,file_path/TEXT,action/TEXT"
    "|epic_tasks:id/INTEGER,epic_id/INTEGER,task_num/INTEGER,title/TEXT,item_worktree_id/INTEGER,context_estimate/TEXT,dependencies/TEXT,status/TEXT,dispatch_attempts/INTEGER,scope_state/TEXT,scope_finalized_at/TIMESTAMPTZ,body/TEXT,github_issue/TEXT,max_attempts/INTEGER,agent_id/TEXT,last_heartbeat/TIMESTAMPTZ,last_activity_at/TIMESTAMPTZ"
    "|event_registry:event_name/TEXT,event_kind/TEXT,event_type/TEXT,owner_service/TEXT,description/TEXT,context_schema/TEXT,severity_default/TEXT,added_in/TEXT,status/TEXT"
    "|events:id/INTEGER,event_id/TEXT,source_type/TEXT,session_id/TEXT,severity/TEXT,event_kind/TEXT,event_type/TEXT,event_name/TEXT,event_outcome/TEXT,org_id/TEXT,actor_id/INTEGER,environment/TEXT,service/TEXT,project_id/INTEGER,item_id/TEXT,task_num/INTEGER,agent/TEXT,tool_name/TEXT,duration_ms/INTEGER,exit_code/INTEGER,trace_id/TEXT,anomaly_flags/TEXT,tool_use_id/TEXT,turn_id/TEXT,hook_event_name/TEXT,client_timing_id/TEXT,envelope/TEXT,created_at/TIMESTAMPTZ"
    "|frontend_attribution_redemptions:org_id/INTEGER,nonce/TEXT,expires_at/TIMESTAMPTZ"
    "|frontend_event_rate_limits:client_key/TEXT,window_start/INTEGER,request_count/INTEGER"
    "|function_call_ledger:request_id/TEXT,function_id/TEXT,actor_id/TEXT,authorization_scope/TEXT,payload_checksum/TEXT,result/TEXT,created_at/TIMESTAMPTZ"
    "|github_app_installations:installation_id/TEXT,api_url/TEXT,account_id/TEXT,account_login/TEXT,account_type/TEXT,repository_selection/TEXT,permissions/TEXT,status/TEXT,last_verified_at/TIMESTAMPTZ,last_error/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|github_workflow_dispatch_intents:request_id/TEXT,attempt/INTEGER,actor_id/TEXT,authorization_scope/TEXT,payload_checksum/TEXT,repo/TEXT,workflow/TEXT,workflow_ref/TEXT,inputs/TEXT,correlation_id/TEXT,state/TEXT,workflow_run_id/TEXT,run_url/TEXT,html_url/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|harness_machine_reports:project_id/INTEGER,machine_id/TEXT,harness_id/TEXT,glue_written/INTEGER,glue_present/INTEGER,glue_malformed/INTEGER,config_present/INTEGER,project_entry_present/INTEGER,approval_state/TEXT,unattended_posture/TEXT,reported_at/TIMESTAMPTZ"
    "|harness_sessions:session_id/TEXT,executor/TEXT,executor_surface/TEXT,presentation_surface/TEXT,presentation_state/TEXT,presentation_mode/TEXT,presentation_source/TEXT,presentation_observed_at/TIMESTAMPTZ,executor_version/TEXT,machine_id/TEXT,provider/TEXT,requested_model/TEXT,requested_reasoning_effort/TEXT,requested_context_window_tokens/INTEGER,model/TEXT,reasoning_effort/TEXT,context_window_tokens/INTEGER,usage_totals/TEXT,execution_level/TEXT,workspace/TEXT,project_id/INTEGER,mode/TEXT,quiet_reason/TEXT,offered_at/TIMESTAMPTZ,last_heartbeat/TIMESTAMPTZ,turn_posture/TEXT,turn_posture_at/TIMESTAMPTZ,ended_at/TIMESTAMPTZ,terminated_at/TIMESTAMPTZ,terminated_by_actor_id/INTEGER,terminated_by_session_id/TEXT,termination_reason/TEXT,offer_envelope/TEXT,current_item_id/TEXT,current_item_set_at/TIMESTAMPTZ,recent_item_id/TEXT,recent_item_status/TEXT,recent_item_recorded_at/TIMESTAMPTZ,last_seen_main_sha/TEXT,last_drift_check_at/TIMESTAMPTZ,last_tool_call_at/TIMESTAMPTZ,tool_call_count/INTEGER,episode_started_at/TIMESTAMPTZ,native_process_gone_at/TIMESTAMPTZ,native_process_gone_evidence/TEXT,pending_resume_notice/TEXT,last_chain_step/INTEGER,last_checkpoint_at/TIMESTAMPTZ,last_steering_report_at/TIMESTAMPTZ,first_user_prompt_at/TIMESTAMPTZ,first_completed_work_at/TIMESTAMPTZ,last_completed_work_at/TIMESTAMPTZ,native_turn_end_recorded_at/TIMESTAMPTZ,native_turn_end_observation/TEXT,vendor_resume_episode_key/TEXT,vendor_resume_attempts/INTEGER,last_steering_report_fingerprint/TEXT,actor_id/INTEGER,native_thread_id/TEXT,keepalive_until/TIMESTAMPTZ,keepalive_reason/TEXT"
    "|item_activity_days:id/INTEGER,project_id/INTEGER,item_id/INTEGER,day/TEXT"
    "|item_dependencies:id/INTEGER,dependent_item_id/INTEGER,blocking_item_id/INTEGER,gate_point/TEXT,satisfaction/TEXT,source/TEXT,session_id/INTEGER,rationale/TEXT,evidence_json/TEXT,created_at/TIMESTAMPTZ"
    "|item_gate_satisfactions:id/INTEGER,item_id/INTEGER,obligation/TEXT,rung_id/TEXT,target_status/TEXT,detail/TEXT,facts/TEXT,recorded_at/TIMESTAMPTZ,recorded_by_session_id/TEXT"
    "|item_landings:id/INTEGER,item_id/INTEGER,merge_sha/TEXT,candidate_sha/TEXT,pr_number/TEXT,target_branch/TEXT,route/TEXT,landed_at/TIMESTAMPTZ,origin/TEXT"
    "|item_sections:item_id/INTEGER,section_name/TEXT,content/TEXT,ordering/INTEGER,source/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|item_status_transitions:id/INTEGER,item_id/INTEGER,task_num/INTEGER,from_status/TEXT,to_status/TEXT,source/TEXT,session_id/TEXT,actor_id/INTEGER,project_id/INTEGER,created_at/TIMESTAMPTZ"
    "|item_strategy_docs:item_id/INTEGER,project_id/INTEGER,strategy_doc_slug/TEXT,linked_by_actor_id/INTEGER,linked_by_session_id/TEXT,linked_at/TIMESTAMPTZ"
    "|item_worktrees:id/INTEGER,item_id/INTEGER,branch/TEXT,path/TEXT,commit_sha/TEXT,lane_role/TEXT,state/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ,released_at/TIMESTAMPTZ"
    "|items:id/INTEGER,title/TEXT,status/TEXT,priority/TEXT,frozen/INTEGER,blocked/INTEGER,blocked_reason/TEXT,github_issue/TEXT,deployed_to/TEXT,merged_at/TIMESTAMPTZ,merge_queue_pr_number/TEXT,merge_queue_enqueued_at/TIMESTAMPTZ,merge_queue_landed_at/TIMESTAMPTZ,merge_queue_notified_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ,source/TEXT,project_id/INTEGER,project_sequence/INTEGER,spec_updated_at/TIMESTAMPTZ,spec_updated_by/TEXT,workflow_id/TEXT,workflow_version_id/INTEGER,workflow_posture/TEXT,generated_task_membership_finalized_at/TIMESTAMPTZ,deployment_flow/TEXT,deploy_stage/TEXT,owner/TEXT,resolution/TEXT,resolution_ref/TEXT,resolution_comment/TEXT,spec/TEXT,design_spec/TEXT,technical_plan/TEXT,worktree_plan/TEXT,shepherd_log/TEXT,shepherd_caveats/TEXT,test_results/TEXT,deploy_log/TEXT,db_mutation_profile/TEXT,db_compatibility_attestation/TEXT,github_body_compact_pending/TIMESTAMPTZ,architecture_impact/TEXT"
    "|machine_authorization_codes:device_hash/TEXT,user_code/TEXT,org_id/INTEGER,expires_at/TIMESTAMPTZ,actor_id/INTEGER,machine_id/TEXT,machine_name/TEXT,consumed_at/TIMESTAMPTZ,client_key/TEXT"
    "|machine_authorization_rate_limits:client_key/TEXT,operation/TEXT,window_start/INTEGER,request_count/INTEGER"
    "|machines:machine_id/TEXT,name/TEXT,owner_actor_id/INTEGER,access/TEXT,registered_at/TIMESTAMPTZ,last_seen_at/TIMESTAMPTZ,retired_at/TIMESTAMPTZ,retired_by_actor_id/INTEGER"
    "|merge_locks:id/INTEGER,session_id/TEXT,branch/TEXT,epic_id/TEXT,acquired_at/TIMESTAMPTZ,expires_at/TIMESTAMPTZ,project_slug/TEXT,target_branch/TEXT"
    "|merge_queue_landing_records:item_id/INTEGER,project_id/INTEGER,pr_number/TEXT,state/TEXT,head_sha/TEXT,queue_holding/TEXT,queue_entry_state/TEXT,merge_when_ready/TEXT,failed_checks/TEXT,narrative/TEXT,disarm_note/TEXT,observed_at/TIMESTAMPTZ,changed_at/TIMESTAMPTZ"
    "|merge_queue_landing_refreshes:project_id/INTEGER,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,last_error/TEXT"
    "|migration_audit:id/BIGINT,migration_name/TEXT,description/TEXT,tables_declared/TEXT,expected_deltas/TEXT,pre_row_counts/TEXT,post_row_counts/TEXT,pre_fk_violations/INTEGER,post_fk_violations/INTEGER,backup_path/TEXT,state/TEXT,failure_reason/TEXT,exception_reason/TEXT,source_fingerprint/TEXT,rehearsed_at/TIMESTAMPTZ,lease_id/INTEGER,test_copy_path/TEXT,baseline_verify_result/TEXT,author_verify_result/TEXT,session_id/TEXT,model_name/TEXT,project_id/INTEGER,actor_id/TEXT,worktree/TEXT,source_branch/TEXT,source_commit/TEXT,integration_target/TEXT,change_class/TEXT,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,duration_ms/INTEGER"
    "|migration_content_adoptions:migration_name/TEXT,content_sha256/TEXT,artifact_engine_version/TEXT,source_artifact/TEXT,source_sha256/TEXT,source_commit/TEXT,manifest_sha256/TEXT,adopted_by/TEXT,adopted_at/TIMESTAMPTZ"
    "|model_reference_revisions:revision_id/TEXT,effective_at/TIMESTAMPTZ,published_at/TIMESTAMPTZ,published_by_actor_id/INTEGER,catalog_json/TEXT,source_note/TEXT,source_revision_id/TEXT"
    "|organizations:id/INTEGER,slug/TEXT,name/TEXT,domain/TEXT,settings/TEXT,created_at/TIMESTAMPTZ,events_signing_key/TEXT"
    "|ouroboros_entries:id/INTEGER,timestamp/TIMESTAMPTZ,agent/TEXT,context/TEXT,category/TEXT,body/TEXT,reviewed_at/TIMESTAMPTZ,archived_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,project_id/INTEGER,target_project_id/INTEGER"
    "|ouroboros_entry_corrections:correction_entry_id/INTEGER,corrected_entry_id/INTEGER,created_at/TIMESTAMPTZ"
    "|ouroboros_entry_dispositions:entry_id/INTEGER,disposition_kind/TEXT,state/TEXT,item_id/INTEGER,title/TEXT,instruction/TEXT,requested_by_actor_id/INTEGER,requested_by_session_id/TEXT,project_override/TEXT,failure_reason/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|overview_activation_facts:id/INTEGER,module_key/TEXT,activated_at/TIMESTAMPTZ"
    "|overview_machine_activation_facts:id/INTEGER,machine_id/TEXT,module_key/TEXT,activated_at/TIMESTAMPTZ"
    "|pack_catalog:slug/TEXT,name/TEXT,description/TEXT,latest_version/TEXT,dependencies_json/TEXT,documentation/TEXT,file_count/INTEGER,observed_at/TIMESTAMPTZ"
    "|path_claim_amendments:id/INTEGER,claim_id/INTEGER,amended_at/TIMESTAMPTZ,amendment_kind/TEXT,payload/TEXT,reason/TEXT"
    "|path_claim_overrides:id/INTEGER,path_claim_id/INTEGER,blocking_claim_id/INTEGER,blocking_path_targets/TEXT,override_point/TEXT,conflict_reason/TEXT,integration_target/TEXT,actor_id/INTEGER,actor_reason/TEXT,item_id/INTEGER,project/TEXT,session_id/TEXT,created_at/TIMESTAMPTZ"
    "|path_claim_targets:id/INTEGER,claim_id/INTEGER,target_id/INTEGER,declared_at/TIMESTAMPTZ"
    "|path_claim_task_bindings:claim_id/INTEGER,epic_id/INTEGER,task_num/INTEGER,bound_at/TIMESTAMPTZ"
    "|path_claims:id/INTEGER,state/TEXT,mode/TEXT,owner_kind/TEXT,owner_item_id/INTEGER,owner_session_id/TEXT,owner_work_claim_id/INTEGER,registered_by_actor_id/INTEGER,registered_by_session_id/TEXT,integration_target/TEXT,base_commit_sha/TEXT,registered_at/TIMESTAMPTZ,activated_at/TIMESTAMPTZ,released_at/TIMESTAMPTZ,cancelled_at/TIMESTAMPTZ,release_reason/TEXT,cancel_reason/TEXT,blocked_reason/TEXT,exception_reason/TEXT"
    "|path_context_values:id/INTEGER,target_id/INTEGER,context_family/TEXT,entry_key/TEXT,value/TEXT,recorded_event_id/TEXT,recorded_at/TIMESTAMPTZ"
    "|path_integrity_failures:id/INTEGER,run_id/INTEGER,invariant_kind/TEXT,target_id/INTEGER,details/TEXT,repair_status/TEXT,recorded_at/TIMESTAMPTZ"
    "|path_integrity_fixtures:id/INTEGER,name/TEXT,description/TEXT,seeded_at/TIMESTAMPTZ,project_id/INTEGER,expected_invariant_kind/TEXT"
    "|path_integrity_repairs:id/INTEGER,failure_id/INTEGER,operation/TEXT,status/TEXT,requested_at/TIMESTAMPTZ,applied_at/TIMESTAMPTZ,error_text/TEXT,arguments/TEXT,recorded_event_id/TEXT,abandon_reason/TEXT"
    "|path_integrity_runs:id/INTEGER,project_id/INTEGER,commit_sha/TEXT,status/TEXT,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,skip_reason/TEXT,block_reason/TEXT,abort_reason/TEXT,failure_count/INTEGER,unrepaired_failure_count/INTEGER,verifier_version/TEXT"
    "|path_moves:id/INTEGER,before_target_id/INTEGER,after_target_id/INTEGER,recorded_event_id/TEXT,recorded_at/TIMESTAMPTZ"
    "|path_snapshot_entries:snapshot_id/INTEGER,target_id/INTEGER,line_count/INTEGER,language/TEXT,module_name/TEXT,area/TEXT,is_generated/INTEGER,dependency_edges/TEXT"
    "|path_snapshot_symlink_facts:snapshot_id/INTEGER,symlink_path/TEXT,symlink_target_id/INTEGER,reason/TEXT,target_attempt/TEXT,canonical_path/TEXT,canonical_target_id/INTEGER"
    "|path_snapshot_sync_upload_chunks:upload_id/TEXT,chunk_index/INTEGER,files_json/TEXT"
    "|path_snapshot_sync_uploads:upload_id/TEXT,project_ref/TEXT,repo_root/TEXT,ref/TEXT,commit_sha/TEXT,expected_file_count/INTEGER,expected_chunk_count/INTEGER,warnings_json/TEXT,symlinks_json/TEXT,created_at/TIMESTAMPTZ"
    "|path_snapshots:id/INTEGER,project_id/INTEGER,commit_sha/TEXT,built_at/TIMESTAMPTZ"
    "|path_targets:id/INTEGER,project_id/INTEGER,kind/TEXT,path_string/TEXT,generation/INTEGER,parent_target_id/INTEGER,created_at/TIMESTAMPTZ,materialization_state/TEXT,materialization_updated_at/TIMESTAMPTZ,planned_by_item_id/INTEGER,planned_by_claim_id/INTEGER"
    "|permissions:id/INTEGER,key/TEXT,description/TEXT,created_at/TIMESTAMPTZ"
    "|project_capabilities:id/INTEGER,project_id/INTEGER,type/TEXT,settings/TEXT,verified_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ"
    "|project_code_days:id/INTEGER,project_id/INTEGER,day/TEXT,commit_count/INTEGER,lines_changed/INTEGER"
    "|project_derived_facts:id/INTEGER,project_id/INTEGER,fact_key/TEXT,present/INTEGER,fact_value/TEXT,observed_at/TIMESTAMPTZ,observed_from/TEXT"
    "|project_github_repo_bindings:project_id/INTEGER,installation_id/TEXT,repository_id/TEXT,api_url/TEXT,github_repo/TEXT,default_branch/TEXT,repository_is_private/BOOLEAN,status/TEXT,permissions/TEXT,last_verified_at/TIMESTAMPTZ,last_error/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ,last_sync_at/TIMESTAMPTZ,last_sync_outcome/TEXT,last_sync_error/TEXT"
    "|project_onboarding_checklist_rows:run_id/TEXT,row_id/TEXT,step/TEXT,title/TEXT,layer/TEXT,owner/TEXT,status/TEXT,hint/TEXT,evidence_json/TEXT,blocker/TEXT,note/TEXT,updated_at/TIMESTAMPTZ"
    "|project_onboarding_runs:run_id/TEXT,schema_version/INTEGER,project_id/INTEGER,branch/TEXT,checkout_path/TEXT,machine_config_path/TEXT,github_repo/TEXT,status/TEXT,metadata_json/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|project_pack_report_entries:project_id/INTEGER,pack_slug/TEXT,installed_version/TEXT,file_count/INTEGER"
    "|project_pack_reports:project_id/INTEGER,receipt_digest/TEXT,pack_count/INTEGER,reported_at/TIMESTAMPTZ"
    "|project_structure:id/INTEGER,project_id/INTEGER,family/TEXT,attachment_value/TEXT,attachment_kind/TEXT,entry_key/TEXT,payload/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|projects:id/INTEGER,slug/TEXT,name/TEXT,emoji/TEXT,default_branch/TEXT,github_repo/TEXT,public_item_prefix/TEXT,github_sync_mode/TEXT,retired_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,org_id/INTEGER,breakage_policy/TEXT"
    "|qa_artifacts:id/INTEGER,qa_run_id/INTEGER,artifact_type/TEXT,content_type/TEXT,artifact_handle/TEXT,metadata/TEXT,created_at/TIMESTAMPTZ"
    "|qa_methods:id/TEXT,name/TEXT,description/TEXT,source_kind/TEXT,source_ref/TEXT,project_id/INTEGER,runner_id/TEXT,required_capability_kinds/TEXT,verdict_path/TEXT,verdict_contract/TEXT,evidence_contract/TEXT,success_policy_id/TEXT,success_policy_params/TEXT,concurrency_mode/TEXT,display_icon/TEXT,display_order/INTEGER,display_group/TEXT,config_contract_id/TEXT,proof_kind/TEXT,runner_gloss/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|qa_plan_cases:id/INTEGER,plan_id/INTEGER,case_key/TEXT,position/INTEGER,method_id/TEXT,instructions/TEXT,expected_outcome/TEXT,method_config/TEXT,success_policy_id/TEXT,success_policy_params/TEXT,host_baselines/TEXT,target_envs/TEXT,entry_surface/TEXT,required_completion/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ,starting_state/TEXT,starting_state_reason/TEXT"
    "|qa_plan_execution_results:execution_id/TEXT,ordinal/INTEGER,requirement_id/INTEGER,result_json/TEXT,completed_at/TIMESTAMPTZ"
    "|qa_plan_executions:id/TEXT,execution_order/BIGINT,item_id/INTEGER,deployment_run_id/TEXT,standalone_plan_id/INTEGER,transition_id/TEXT,actor_id/TEXT,session_id/TEXT,roster_digest/TEXT,roster_json/TEXT,execution_target_json/TEXT,execution_target_digest/TEXT,continues_execution_id/TEXT,cursor_ordinal/INTEGER,state/TEXT,machine_lease_id/INTEGER,created_at/TIMESTAMPTZ,heartbeat_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,release_reason/TEXT,deployment_stage/TEXT,deployment_member_item_id/INTEGER"
    "|qa_plan_item_attachments:item_id/INTEGER,transition_id/TEXT,qa_phase/TEXT,plan_id/INTEGER,attached_at/TIMESTAMPTZ,attached_by_actor_id/INTEGER,retracted_at/TIMESTAMPTZ,retraction_rationale/TEXT,retraction_source/TEXT,retracted_by_actor_id/INTEGER"
    "|qa_plan_project_defaults:project_id/INTEGER,workflow_id/TEXT,transition_id/TEXT,qa_phase/TEXT,plan_id/INTEGER,attached_at/TIMESTAMPTZ,attached_by_actor_id/INTEGER"
    "|qa_plan_review_bundles:id/TEXT,execution_id/TEXT,roster_digest/TEXT,bundle_digest/TEXT,bundle_json/TEXT,state/TEXT,reviewer_actor_id/TEXT,reviewer_session_id/TEXT,created_at/TIMESTAMPTZ,reviewed_at/TIMESTAMPTZ"
    "|qa_plan_review_verdicts:bundle_id/TEXT,requirement_id/INTEGER,capture_run_id/INTEGER,review_run_id/INTEGER,verdict/TEXT,rationale/TEXT,decision_request_id/INTEGER,created_at/TIMESTAMPTZ"
    "|qa_plans:id/INTEGER,project_id/INTEGER,slug/TEXT,name/TEXT,description/TEXT,success_policy_id/TEXT,success_policy_params/TEXT,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ,retired_at/TIMESTAMPTZ,target_environment_id/INTEGER"
    "|qa_requirements:id/INTEGER,item_id/INTEGER,epic_id/INTEGER,task_num/INTEGER,deployment_run_id/TEXT,standalone_execution_id/TEXT,plan_id/INTEGER,workflow_transition_id/TEXT,deployment_stage/TEXT,deployment_member_item_id/INTEGER,qa_kind/TEXT,qa_phase/TEXT,target_env/TEXT,blocking_mode/TEXT,requirement_source/TEXT,success_policy/TEXT,capability_requirements/TEXT,suite_id/TEXT,waived_at/TIMESTAMPTZ,waiver_rationale/TEXT,waiver_source/TEXT,created_at/TIMESTAMPTZ,plan_case_key/TEXT,case_position/INTEGER,baseline_position/INTEGER,method_id/TEXT,method_name/TEXT,runner_id/TEXT,verdict_path/TEXT,host_baseline/TEXT,starting_state/TEXT,starting_state_reason/TEXT,entry_surface/TEXT,required_completion/TEXT,instructions/TEXT,expected_outcome/TEXT,method_config/TEXT,execution_target_json/TEXT,execution_target_digest/TEXT,superseded_by_requirement_id/INTEGER,superseded_at/TIMESTAMPTZ,supersession_rationale/TEXT,supersession_source/TEXT,replacement_requirement_id/INTEGER,retracted_at/TIMESTAMPTZ,retraction_rationale/TEXT,retraction_source/TEXT,rebound_at/TIMESTAMPTZ,rebound_from_digest/TEXT,rebind_rationale/TEXT,rebind_actor_id/INTEGER,rebound_from_target_json/TEXT,rebind_endpoint_delta_json/TEXT"
    "|qa_runs:id/INTEGER,qa_requirement_id/INTEGER,performed_by/TEXT,qa_kind/TEXT,verdict/TEXT,verdict_reason/TEXT,execution_status/TEXT,score/REAL,confidence/REAL,raw_result/TEXT,duration_ms/INTEGER,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,case_outcome/TEXT,capture_degraded_reason/TEXT"
    "|release_entries:id/INTEGER,item_id/INTEGER,category/TEXT,title/TEXT,version/TEXT,project_id/INTEGER,created_at/TIMESTAMPTZ"
    "|role_permissions:role_id/INTEGER,permission_id/INTEGER,created_at/TIMESTAMPTZ"
    "|roles:id/INTEGER,name/TEXT,description/TEXT,created_at/TIMESTAMPTZ"
    "|session_ci_run_waits:id/INTEGER,session_id/TEXT,project_id/INTEGER,repo/TEXT,run_id/TEXT,head_sha/TEXT,kind/TEXT,continue_command/TEXT,created_at/TIMESTAMPTZ,read_at/TIMESTAMPTZ,conclusion/TEXT,notified_at/TIMESTAMPTZ"
    "|session_evidence_fetches:fetch_id/TEXT,target_session_id/TEXT,project_id/INTEGER,machine_id/TEXT,kind/TEXT,file_name/TEXT,diagnostic_ref/TEXT,tail_lines/INTEGER,state/TEXT,requested_at/TIMESTAMPTZ,requested_by_actor_id/INTEGER,requested_by_session_id/TEXT,lease_id/TEXT,lease_expires_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,result_code/TEXT,files/TEXT,selected_file/TEXT,content/TEXT,content_bytes/INTEGER,truncated/INTEGER"
    "|session_launch_attempts:attempt_id/TEXT,launch_id/TEXT,relay_id/TEXT,machine_id/TEXT,lease_id/TEXT,batch_id/TEXT,attempt_number/INTEGER,adapter_revision/TEXT,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,native_session_id/TEXT,result_code/TEXT,evidence/TEXT"
    "|session_launches:launch_id/TEXT,requester_actor_id/INTEGER,requester_session_id/TEXT,project_id/INTEGER,requested_surface/TEXT,selected_surface/TEXT,requested_machine_id/TEXT,requested_model/TEXT,requested_reasoning_effort/TEXT,requested_context_window_tokens/INTEGER,presentation_preference/TEXT,session_name/TEXT,allow_surface_fallback/INTEGER,message_id/TEXT,idempotency_key/TEXT,state/TEXT,assigned_relay_id/TEXT,assigned_machine_id/TEXT,native_session_id/TEXT,attestation_hash/TEXT,attestation_consumed_at/TIMESTAMPTZ,registered_session_id/TEXT,deadline_at/TIMESTAMPTZ,created_at/TIMESTAMPTZ,assigned_at/TIMESTAMPTZ,launching_at/TIMESTAMPTZ,awaiting_registration_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,result_code/TEXT,result_evidence/TEXT,origin/TEXT,native_launch_pid/INTEGER,native_launch_phase/TEXT,native_launch_observed_at/TIMESTAMPTZ,spawn_duration_ms/INTEGER,spawn_hold_reason/TEXT,placement_reason/TEXT,resolved_model/TEXT,resolved_reasoning_effort/TEXT,resolved_context_window_tokens/INTEGER,requested_level/TEXT,level_placement/TEXT"
    "|session_message_attempts:attempt_id/TEXT,message_id/TEXT,target_session_id/TEXT,broker_session_id/TEXT,attempt_kind/TEXT,adapter_revision/TEXT,lease_id/TEXT,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,result_code/TEXT,evidence/TEXT"
    "|session_message_recipients:message_id/TEXT,session_id/TEXT,project_id/INTEGER,resolution_evidence/TEXT,routing_snapshot/TEXT,executor_surface/TEXT,executor_version/TEXT,machine_id/TEXT,state/TEXT,created_at/TIMESTAMPTZ,wake_after/TEXT,injection_lease_id/TEXT,injection_leased_at/TIMESTAMPTZ,injection_lease_expires_at/TIMESTAMPTZ,injection_count/INTEGER,last_injected_at/TIMESTAMPTZ,acknowledged_at/TIMESTAMPTZ,expired_at/TIMESTAMPTZ,cancelled_at/TIMESTAMPTZ,wake_attempt_count/INTEGER,last_wake_at/TIMESTAMPTZ,wake_escalation/TEXT"
    "|session_messages:message_id/TEXT,sender_actor_id/INTEGER,sender_session_id/TEXT,body/TEXT,body_sha256/TEXT,selector_snapshot/TEXT,idempotency_key/TEXT,created_at/TIMESTAMPTZ,expires_at/TIMESTAMPTZ,cancelled_at/TIMESTAMPTZ,cancelled_by_actor_id/INTEGER,cancellation_reason/TEXT,sender_surface/TEXT"
    "|session_promised_work_holds:session_id/TEXT,item_id/INTEGER,hold_count/INTEGER,last_hold_at/TIMESTAMPTZ"
    "|session_relays:relay_id/TEXT,actor_id/INTEGER,machine_id/TEXT,hostname/TEXT,relay_version/TEXT,surface_versions/TEXT,surface_confirmed_absent/TEXT,project_checkouts/TEXT,first_seen_at/TIMESTAMPTZ,last_seen_at/TIMESTAMPTZ,connected_until/TIMESTAMPTZ,last_job_at/TIMESTAMPTZ,state/TEXT,lease_id/TEXT,lease_expires_at/TIMESTAMPTZ,surface_plan_limits/TEXT,machine_capacity/TEXT,relay_health/TEXT,surface_native_models/TEXT,credential_presence/TEXT"
    "|session_surface_policies:mark_id/TEXT,machine_id/TEXT,surface/TEXT,state/TEXT,reason/TEXT,evidence/TEXT,set_by_actor_id/INTEGER,set_by_session_id/TEXT,created_at/TIMESTAMPTZ,cleared_at/TIMESTAMPTZ,cleared_by_actor_id/INTEGER"
    "|session_termination_reaps:target_session_id/TEXT,project_id/INTEGER,machine_id/TEXT,executor_surface/TEXT,target_native_thread_id/TEXT,launch_id/TEXT,state/TEXT,requested_at/TIMESTAMPTZ,lease_id/TEXT,lease_expires_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,result_code/TEXT,evidence/TEXT"
    "|session_tool_calls:id/INTEGER,session_id/TEXT,tool_use_id/TEXT,tool_name/TEXT,started_at/TIMESTAMPTZ,completed_at/TIMESTAMPTZ,outcome/TEXT,command_summary/TEXT"
    "|severity_config:id/INTEGER,event_name/TEXT,source_type/TEXT,min_severity/TEXT,created_at/TIMESTAMPTZ"
    "|shepherd_verdicts:id/INTEGER,public_ref/TEXT,archived_item_key/TEXT,transition/TEXT,worker/TEXT,verdict/TEXT,caveats/TEXT,attempt/INTEGER,created_at/TIMESTAMPTZ"
    "|sites:id/INTEGER,project_id/INTEGER,name/TEXT,description/TEXT,created_at/TIMESTAMPTZ,settings/TEXT"
    "|strategize_landed_carry:item_id/INTEGER,project_id/INTEGER,state/TEXT,first_seen_at/TIMESTAMPTZ,last_updated_at/TIMESTAMPTZ,last_session_id/TEXT,reason/TEXT"
    "|strategy_checkpoints:id/INTEGER,project_id/INTEGER,kind/TEXT,created_at/TIMESTAMPTZ"
    "|strategy_doc_claims:id/INTEGER,project_id/INTEGER,strategy_doc_slug/TEXT,owner_kind/TEXT,owner_item_id/INTEGER,owner_session_id/TEXT,steering_claim_id/INTEGER,registered_by_actor_id/INTEGER,registered_by_session_id/TEXT,registered_at/TIMESTAMPTZ,released_by_actor_id/INTEGER,released_by_session_id/TEXT,released_at/TIMESTAMPTZ,release_mode/TEXT,release_reason/TEXT"
    "|strategy_doc_revisions:id/BIGINT,project_id/BIGINT,slug/TEXT,revision/BIGINT,content/TEXT,content_sha256/TEXT,byte_length/BIGINT,source_operation/TEXT,actor_id/BIGINT,session_id/TEXT,created_at/TIMESTAMPTZ"
    "|strategy_docs:id/BIGINT,project_id/BIGINT,slug/TEXT,content/TEXT,updated_at/TIMESTAMPTZ,updated_by_actor_id/BIGINT,archived_at/TIMESTAMPTZ,parent_slug/TEXT"
    "|test_machine_operation_receipts:project_id/INTEGER,capability_type/TEXT,operation/TEXT,status/TEXT,performed_at/TIMESTAMPTZ,receipt_json/TEXT,error_code/TEXT,lease_id/INTEGER,contract_digest/TEXT,updated_at/TIMESTAMPTZ"
    "|test_machine_verifications:project_id/INTEGER,capability_type/TEXT,status/TEXT,checked_at/TIMESTAMPTZ,receipt_json/TEXT,error_code/TEXT,updated_at/TIMESTAMPTZ"
    "|universe_settings:key/TEXT,value/TEXT,updated_at/TIMESTAMPTZ,updated_by_actor_id/INTEGER"
    "|web_sessions:id/INTEGER,token_hash/TEXT,actor_id/INTEGER,created_at/TIMESTAMPTZ,expires_at/TIMESTAMPTZ,revoked_at/TIMESTAMPTZ,last_used_at/TIMESTAMPTZ"
    "|work_claims:id/INTEGER,session_id/TEXT,target_kind/TEXT,scope/TEXT,claim_type/TEXT,claimed_at/TIMESTAMPTZ,last_heartbeat/TIMESTAMPTZ,released_at/TIMESTAMPTZ,release_reason/TEXT,reason/TEXT,reason_intent/TEXT,release_reason_intent/TEXT"
    "|workflow_execution_instruction_projects:instruction_id/INTEGER,project_id/INTEGER"
    "|workflow_execution_instruction_workflows:instruction_id/INTEGER,workflow_id/TEXT"
    "|workflow_execution_instructions:id/INTEGER,content/TEXT,applies_to_all_workflows/INTEGER,applies_to_all_projects/INTEGER,before_creation/INTEGER,on_every_read/INTEGER,when_entering_stage/INTEGER,stage_buckets/TEXT,updated_by_actor_id/INTEGER,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
    "|workflow_versions:id/INTEGER,workflow_id/TEXT,version/INTEGER,definition_schema_version/INTEGER,definition_json/TEXT,definition_digest/TEXT,published_at/TIMESTAMPTZ,published_by_actor_id/INTEGER,immutable_at/TIMESTAMPTZ,derived_from_canon_version/INTEGER"
    "|workflows:id/TEXT,name/TEXT,description/TEXT,source/TEXT,status/TEXT,canon_follow/TEXT,canon_adopted_from_version/INTEGER,current_version_id/INTEGER,created_at/TIMESTAMPTZ,updated_at/TIMESTAMPTZ"
)


def parse_expected_schema() -> Dict[str, Dict[str, str]]:
    """Return ``{table: {column: type}}`` from the declared string.

    Pure parsing — no DB connection, no PRAGMA. The caller compares the result
    against the live schema and reports drift.
    """
    expected: Dict[str, Dict[str, str]] = {}
    for tbl_spec in _EXPECTED_SCHEMA_STR.split("|"):
        tbl_spec = tbl_spec.strip()
        if not tbl_spec or ":" not in tbl_spec:
            continue
        tbl_name, cols_str = tbl_spec.split(":", 1)
        expected[tbl_name] = {}
        for col_spec in cols_str.split(","):
            if "/" in col_spec:
                cname, ctype = col_spec.split("/", 1)
                expected[tbl_name][cname] = ctype
    return expected
