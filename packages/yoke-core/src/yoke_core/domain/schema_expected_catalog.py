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

Both readers compare NAMES; the type field is descriptive and appears only in
the message a mismatch prints.
"""

from __future__ import annotations

from typing import Dict


_EXPECTED_SCHEMA_STR = (
    "actor_external_identities:id/INTEGER,actor_id/INTEGER,issuer/TEXT,subject/TEXT,email/TEXT,linked_at/TEXT,created_by_actor_id/INTEGER"
    "|actor_invites:id/INTEGER,email/TEXT,org_id/INTEGER,role_id/INTEGER,actor_id/INTEGER,status/TEXT,invited_by_actor_id/INTEGER,created_at/TEXT,accepted_at/TEXT,accepted_by_actor_id/INTEGER"
    "|actor_labels:id/INTEGER,actor_id/INTEGER,surface/TEXT,label/TEXT,created_at/TEXT"
    "|actor_org_roles:actor_id/INTEGER,org_id/INTEGER,role_id/INTEGER,granted_at/TEXT,granted_by_actor_id/INTEGER"
    "|actor_project_roles:actor_id/INTEGER,project_id/INTEGER,role_id/INTEGER,granted_at/TEXT,granted_by_actor_id/INTEGER"
    "|actor_ui_preferences:id/INTEGER,actor_id/INTEGER,pref_key/TEXT,value/TEXT,updated_at/TEXT"
    "|actors:id/INTEGER,kind/TEXT,system_component/TEXT,created_at/TEXT"
    "|addressed_event_deliveries:id/INTEGER,channel/TEXT,event_id/TEXT,actor_id/INTEGER,notification_kind/TEXT,reason/TEXT,read_at/TEXT,created_at/TEXT,event_name/TEXT,project_id/INTEGER,event_outcome/TEXT,event_actor_id/INTEGER,event_actor_label/TEXT,event_envelope/TEXT"
    "|api_token_audit:id/INTEGER,api_token_id/INTEGER,actor_id/INTEGER,project_id/INTEGER,event_type/TEXT,outcome/TEXT,permission_key/TEXT,diagnostic_metadata/TEXT,created_at/TEXT"
    "|api_tokens:id/INTEGER,token_hash/TEXT,actor_id/INTEGER,name/TEXT,status/TEXT,created_at/TEXT,revoked_at/TEXT,expires_at/TEXT,last_used_at/TEXT,diagnostic_metadata/TEXT"
    "|applied_migrations:migration_name/TEXT,applied_at/TEXT,applied_by/TEXT,minimum_serving_version/TEXT,content_sha256/TEXT"
    "|capability_secrets:id/INTEGER,project_id/INTEGER,type/TEXT,key/TEXT,value/TEXT,source/TEXT,created_at/TEXT"
    "|capability_templates:id/TEXT,name/TEXT,description/TEXT,required_config/TEXT,requires/TEXT,created_at/TEXT"
    "|caveat_dispositions:id/INTEGER,item/TEXT,transition/TEXT,attempt/INTEGER,caveat_num/INTEGER,caveat_text/TEXT,disposition/TEXT,resolution_details/TEXT,verdict_id/INTEGER,created_at/TEXT"
    "|decision_request_actor_authorities:request_id/INTEGER,actor_id/INTEGER"
    "|decision_request_role_authorities:request_id/INTEGER,scope_kind/TEXT,scope_id/INTEGER,role_name/TEXT"
    "|decision_requests:id/INTEGER,kind/TEXT,subject_type/TEXT,subject_key/TEXT,subject_context/TEXT,project_id/INTEGER,org_id/INTEGER,originator_actor_id/INTEGER,blocking/INTEGER,status/TEXT,resolution_action/TEXT,resolution_actor_id/INTEGER,resolution_note/TEXT,resolved_at/TEXT,withdrawal_reason/TEXT,withdrawn_at/TEXT,consumed_at/TEXT,consumed_from_stage/TEXT,consumed_to_stage/TEXT,consumed_workflow_version_id/INTEGER,created_at/TEXT"
    "|deployment_flows:id/TEXT,project_id/INTEGER,name/TEXT,description/TEXT,stages/TEXT,on_failure/TEXT,created_at/TEXT,target_tier/TEXT,target_environment_id/INTEGER,done_description/TEXT,status/TEXT"
    "|deployment_preview_environments:id/INTEGER,project_id/INTEGER,env_name/TEXT,run_id/TEXT,status/TEXT,env_type/TEXT,url/TEXT,created_at/TEXT"
    "|deployment_run_items:run_id/TEXT,item_id/INTEGER,added_at/TEXT"
    "|deployment_run_qa:id/INTEGER,run_id/TEXT,check_name/TEXT,source/TEXT,blocking/INTEGER,status/TEXT,updated_at/TEXT"
    "|deployment_runs:id/TEXT,project_id/INTEGER,flow/TEXT,target_tier/TEXT,target_environment_id/INTEGER,release_lineage/TEXT,status/TEXT,current_stage/TEXT,created_at/TEXT,started_at/TEXT,completed_at/TEXT,created_by/TEXT,carried_work/TEXT"
    "|doctor_runs:id/INTEGER,ran_at/TEXT,project/TEXT,scope/TEXT,runtime/TEXT,fail_count/INTEGER,pass_count/INTEGER,warn_count/INTEGER,na_count/INTEGER,results/TEXT"
    "|environments:id/INTEGER,site/INTEGER,project_id/INTEGER,name/TEXT,url/TEXT,deploy_method/TEXT,deploy_command/TEXT,health_check_url/TEXT,config_notes/TEXT,last_deployed_at/TEXT,created_at/TEXT,settings/TEXT"
    "|ephemeral_environments:id/INTEGER,project_id/INTEGER,branch/TEXT,item/TEXT,workflow_run_id/TEXT,github_ref/TEXT,port_api/INTEGER,port_web/INTEGER,url/TEXT,status/TEXT,started_at/TEXT,stopped_at/TEXT,health_check_url/TEXT,deployed_sha/TEXT,created_at/TEXT"
    "|epic_dispatch_chains:id/INTEGER,epic_id/INTEGER,queue/TEXT,current_index/INTEGER,current_task/TEXT,current_attempt/INTEGER,max_attempts/INTEGER,no_chain/INTEGER,started_at/TEXT,last_updated/TEXT,item_worktree_id/INTEGER"
    "|epic_progress_notes:id/INTEGER,epic_id/INTEGER,task_num/INTEGER,note_num/INTEGER,body/TEXT,commit_hash/TEXT,synced_to_github/INTEGER,created_at/TEXT"
    "|epic_task_files:id/INTEGER,epic_id/INTEGER,task_num/INTEGER,file_path/TEXT,action/TEXT"
    "|epic_tasks:id/INTEGER,epic_id/INTEGER,task_num/INTEGER,title/TEXT,context_estimate/TEXT,dependencies/TEXT,status/TEXT,dispatch_attempts/INTEGER,body/TEXT,github_issue/TEXT,max_attempts/INTEGER,agent_id/TEXT,last_heartbeat/TEXT,last_activity_at/TEXT,item_worktree_id/INTEGER,scope_state/TEXT,scope_finalized_at/TEXT"
    "|event_registry:event_name/TEXT,event_kind/TEXT,event_type/TEXT,owner_service/TEXT,description/TEXT,context_schema/TEXT,severity_default/TEXT,added_in/TEXT,status/TEXT"
    "|events:id/INTEGER,event_id/TEXT,source_type/TEXT,session_id/TEXT,severity/TEXT,event_kind/TEXT,event_type/TEXT,event_name/TEXT,event_outcome/TEXT,org_id/TEXT,actor_id/INTEGER,environment/TEXT,service/TEXT,project_id/INTEGER,item_id/TEXT,task_num/INTEGER,agent/TEXT,tool_name/TEXT,duration_ms/INTEGER,exit_code/INTEGER,trace_id/TEXT,anomaly_flags/TEXT,tool_use_id/TEXT,turn_id/TEXT,hook_event_name/TEXT,envelope/TEXT,created_at/TEXT"
    "|function_call_ledger:request_id/TEXT,function_id/TEXT,actor_id/TEXT,authorization_scope/TEXT,payload_checksum/TEXT,result/TEXT,created_at/TEXT"
    "|github_app_installations:installation_id/TEXT,api_url/TEXT,account_id/TEXT,account_login/TEXT,account_type/TEXT,repository_selection/TEXT,permissions/TEXT,status/TEXT,last_verified_at/TEXT,last_error/TEXT,created_at/TEXT,updated_at/TEXT"
    "|github_workflow_dispatch_intents:request_id/TEXT,attempt/INTEGER,actor_id/TEXT,authorization_scope/TEXT,payload_checksum/TEXT,repo/TEXT,workflow/TEXT,workflow_ref/TEXT,inputs/TEXT,correlation_id/TEXT,state/TEXT,workflow_run_id/TEXT,run_url/TEXT,html_url/TEXT,created_at/TEXT,updated_at/TEXT"
    "|harness_machine_reports:project_id/INTEGER,harness_id/TEXT,glue_written/INTEGER,glue_present/INTEGER,glue_malformed/INTEGER,config_present/INTEGER,project_entry_present/INTEGER,approval_state/TEXT,reported_at/TEXT"
    "|harness_sessions:session_id/TEXT,executor/TEXT,executor_surface/TEXT,presentation_surface/TEXT,presentation_state/TEXT,presentation_mode/TEXT,presentation_source/TEXT,presentation_observed_at/TEXT,executor_version/TEXT,machine_id/TEXT,provider/TEXT,model/TEXT,execution_lane/TEXT,workspace/TEXT,project_id/INTEGER,mode/TEXT,parked_reason/TEXT,keepalive_until/TEXT,keepalive_reason/TEXT,offered_at/TEXT,last_heartbeat/TEXT,turn_posture/TEXT,turn_posture_at/TEXT,ended_at/TEXT,terminated_at/TEXT,terminated_by_actor_id/INTEGER,terminated_by_session_id/TEXT,termination_reason/TEXT,offer_envelope/TEXT,current_item_id/TEXT,current_item_set_at/TEXT,recent_item_id/TEXT,recent_item_status/TEXT,recent_item_recorded_at/TEXT,last_seen_main_sha/TEXT,last_drift_check_at/TEXT,last_tool_call_at/TEXT,tool_call_count/INTEGER,episode_started_at/TEXT,pending_resume_notice/TEXT,last_chain_step/INTEGER,last_checkpoint_at/TEXT,actor_id/INTEGER,native_thread_id/TEXT,last_steering_report_at/TEXT,last_steering_report_fingerprint/TEXT"
    "|item_activity_days:id/INTEGER,project_id/INTEGER,item_id/INTEGER,day/TEXT"
    "|project_code_days:id/INTEGER,project_id/INTEGER,day/TEXT,"
    "commit_count/INTEGER,lines_changed/INTEGER"
    "|item_dependencies:id/INTEGER,dependent_item_id/INTEGER,blocking_item_id/INTEGER,gate_point/TEXT,satisfaction/TEXT,source/TEXT,session_id/INTEGER,rationale/TEXT,evidence_json/TEXT,created_at/TEXT"
    "|item_sections:item_id/INTEGER,section_name/TEXT,content/TEXT,ordering/INTEGER,source/TEXT,created_at/TEXT,updated_at/TEXT"
    "|item_status_transitions:id/INTEGER,item_id/INTEGER,task_num/INTEGER,from_status/TEXT,to_status/TEXT,source/TEXT,session_id/TEXT,actor_id/INTEGER,project_id/INTEGER,created_at/TEXT"
    "|item_strategy_docs:item_id/INTEGER,project_id/INTEGER,strategy_doc_slug/TEXT,linked_by_actor_id/INTEGER,linked_by_session_id/TEXT,linked_at/TEXT"
    "|item_worktrees:id/INTEGER,item_id/INTEGER,branch/TEXT,path/TEXT,commit_sha/TEXT,lane_role/TEXT,state/TEXT,created_at/TEXT,updated_at/TEXT,released_at/TEXT"
    "|items:id/INTEGER,title/TEXT,status/TEXT,priority/TEXT,frozen/INTEGER,blocked/INTEGER,blocked_reason/TEXT,github_issue/TEXT,deployed_to/TEXT,merged_at/TEXT,merge_queue_pr_number/TEXT,merge_queue_enqueued_at/TEXT,merge_queue_landed_at/TEXT,merge_queue_notified_at/TEXT,created_at/TEXT,updated_at/TEXT,source/TEXT,project_id/INTEGER,project_sequence/INTEGER,spec_updated_at/TEXT,spec_updated_by/TEXT,deployment_flow/TEXT,deploy_stage/TEXT,owner/TEXT,resolution/TEXT,resolution_ref/TEXT,resolution_comment/TEXT,spec/TEXT,design_spec/TEXT,technical_plan/TEXT,worktree_plan/TEXT,shepherd_log/TEXT,shepherd_caveats/TEXT,test_results/TEXT,deploy_log/TEXT,db_mutation_profile/TEXT,db_compatibility_attestation/TEXT,github_body_compact_pending/TEXT,architecture_impact/TEXT,workflow_id/TEXT,workflow_version_id/INTEGER,workflow_posture/TEXT,generated_task_membership_finalized_at/TEXT"
    "|merge_locks:id/INTEGER,session_id/TEXT,branch/TEXT,epic_id/TEXT,acquired_at/TEXT,expires_at/TEXT,project_slug/TEXT,target_branch/TEXT"
    "|migration_audit:id/INTEGER,migration_name/TEXT,description/TEXT,tables_declared/TEXT,expected_deltas/TEXT,pre_row_counts/TEXT,post_row_counts/TEXT,pre_fk_violations/INTEGER,post_fk_violations/INTEGER,backup_path/TEXT,state/TEXT,failure_reason/TEXT,exception_reason/TEXT,source_fingerprint/TEXT,rehearsed_at/TEXT,lease_id/INTEGER,test_copy_path/TEXT,baseline_verify_result/TEXT,author_verify_result/TEXT,session_id/TEXT,model_name/TEXT,project_id/INTEGER,actor_id/TEXT,worktree/TEXT,source_branch/TEXT,source_commit/TEXT,integration_target/TEXT,change_class/TEXT,started_at/TEXT,completed_at/TEXT,duration_ms/INTEGER"
    "|migration_content_adoptions:migration_name/TEXT,content_sha256/TEXT,artifact_engine_version/TEXT,source_artifact/TEXT,source_sha256/TEXT,source_commit/TEXT,manifest_sha256/TEXT,adopted_by/TEXT,adopted_at/TEXT"
    "|organizations:id/INTEGER,slug/TEXT,name/TEXT,domain/TEXT,settings/TEXT,created_at/TEXT"
    "|ouroboros_entries:id/INTEGER,timestamp/TEXT,agent/TEXT,context/TEXT,category/TEXT,body/TEXT,reviewed_at/TEXT,archived_at/TEXT,created_at/TEXT,project_id/INTEGER,target_project_id/INTEGER"
    "|ouroboros_entry_corrections:correction_entry_id/INTEGER,corrected_entry_id/INTEGER,created_at/TEXT"
    "|ouroboros_entry_dispositions:entry_id/INTEGER,disposition_kind/TEXT,state/TEXT,item_id/INTEGER,title/TEXT,instruction/TEXT,requested_by_actor_id/INTEGER,requested_by_session_id/TEXT,project_override/TEXT,failure_reason/TEXT,created_at/TEXT,updated_at/TEXT"
    "|overview_activation_facts:id/INTEGER,module_key/TEXT,activated_at/TEXT"
    "|pack_catalog:slug/TEXT,name/TEXT,description/TEXT,latest_version/TEXT,dependencies_json/TEXT,documentation/TEXT,file_count/INTEGER,observed_at/TEXT"
    "|path_claim_amendments:id/INTEGER,claim_id/INTEGER,amended_at/TEXT,amendment_kind/TEXT,payload/TEXT,reason/TEXT"
    "|path_claim_overrides:id/INTEGER,path_claim_id/INTEGER,blocking_claim_id/INTEGER,blocking_path_targets/TEXT,override_point/TEXT,conflict_reason/TEXT,integration_target/TEXT,actor_id/INTEGER,actor_reason/TEXT,item_id/INTEGER,project/TEXT,session_id/TEXT,created_at/TEXT"
    "|path_claim_targets:id/INTEGER,claim_id/INTEGER,target_id/INTEGER,declared_at/TEXT"
    "|path_claim_task_bindings:claim_id/INTEGER,epic_id/INTEGER,task_num/INTEGER,bound_at/TEXT"
    "|path_claims:id/INTEGER,state/TEXT,mode/TEXT,owner_kind/TEXT,owner_item_id/INTEGER,owner_session_id/TEXT,owner_work_claim_id/INTEGER,registered_by_actor_id/INTEGER,registered_by_session_id/TEXT,integration_target/TEXT,base_commit_sha/TEXT,registered_at/TEXT,activated_at/TEXT,released_at/TEXT,cancelled_at/TEXT,release_reason/TEXT,cancel_reason/TEXT,blocked_reason/TEXT,exception_reason/TEXT"
    "|path_context_values:id/INTEGER,target_id/INTEGER,context_family/TEXT,entry_key/TEXT,value/TEXT,recorded_event_id/TEXT,recorded_at/TEXT"
    "|path_integrity_failures:id/INTEGER,run_id/INTEGER,invariant_kind/TEXT,target_id/INTEGER,details/TEXT,repair_status/TEXT,recorded_at/TEXT"
    "|path_integrity_fixtures:id/INTEGER,name/TEXT,description/TEXT,seeded_at/TEXT,project_id/INTEGER,expected_invariant_kind/TEXT"
    "|path_integrity_repairs:id/INTEGER,failure_id/INTEGER,operation/TEXT,status/TEXT,requested_at/TEXT,applied_at/TEXT,error_text/TEXT,arguments/TEXT,recorded_event_id/TEXT,abandon_reason/TEXT"
    "|path_integrity_runs:id/INTEGER,project_id/INTEGER,commit_sha/TEXT,status/TEXT,started_at/TEXT,completed_at/TEXT,skip_reason/TEXT,block_reason/TEXT,abort_reason/TEXT,failure_count/INTEGER,unrepaired_failure_count/INTEGER,verifier_version/TEXT"
    "|path_moves:id/INTEGER,before_target_id/INTEGER,after_target_id/INTEGER,recorded_event_id/TEXT,recorded_at/TEXT"
    "|path_snapshot_entries:snapshot_id/INTEGER,target_id/INTEGER,line_count/INTEGER,language/TEXT,module_name/TEXT,area/TEXT,is_generated/INTEGER,dependency_edges/TEXT"
    "|path_snapshot_symlink_facts:snapshot_id/INTEGER,symlink_path/TEXT,symlink_target_id/INTEGER,reason/TEXT,target_attempt/TEXT,canonical_path/TEXT,canonical_target_id/INTEGER"
    "|path_snapshot_sync_upload_chunks:upload_id/TEXT,chunk_index/INTEGER,files_json/TEXT"
    "|path_snapshot_sync_uploads:upload_id/TEXT,project_ref/TEXT,repo_root/TEXT,ref/TEXT,commit_sha/TEXT,expected_file_count/INTEGER,expected_chunk_count/INTEGER,warnings_json/TEXT,symlinks_json/TEXT,created_at/TEXT"
    "|path_snapshots:id/INTEGER,project_id/INTEGER,commit_sha/TEXT,built_at/TEXT"
    "|path_targets:id/INTEGER,project_id/INTEGER,kind/TEXT,path_string/TEXT,generation/INTEGER,parent_target_id/INTEGER,created_at/TEXT,materialization_state/TEXT,materialization_updated_at/TEXT,planned_by_item_id/INTEGER,planned_by_claim_id/INTEGER"
    "|permissions:id/INTEGER,key/TEXT,description/TEXT,created_at/TEXT"
    "|project_capabilities:id/INTEGER,project_id/INTEGER,type/TEXT,settings/TEXT,verified_at/TEXT,created_at/TEXT"
    "|project_github_repo_bindings:project_id/INTEGER,installation_id/TEXT,repository_id/TEXT,api_url/TEXT,github_repo/TEXT,default_branch/TEXT,status/TEXT,permissions/TEXT,last_verified_at/TEXT,last_error/TEXT,created_at/TEXT,updated_at/TEXT,last_sync_at/TEXT,last_sync_outcome/TEXT,last_sync_error/TEXT,repository_is_private/TEXT"
    "|project_onboarding_checklist_rows:run_id/TEXT,row_id/TEXT,step/TEXT,title/TEXT,layer/TEXT,owner/TEXT,status/TEXT,hint/TEXT,evidence_json/TEXT,blocker/TEXT,note/TEXT,updated_at/TEXT"
    "|project_onboarding_runs:run_id/TEXT,schema_version/INTEGER,project_id/INTEGER,branch/TEXT,checkout_path/TEXT,machine_config_path/TEXT,github_repo/TEXT,status/TEXT,metadata_json/TEXT,created_at/TEXT,updated_at/TEXT"
    "|project_pack_report_entries:project_id/INTEGER,pack_slug/TEXT,installed_version/TEXT,file_count/INTEGER"
    "|project_pack_reports:project_id/INTEGER,receipt_digest/TEXT,pack_count/INTEGER,reported_at/TEXT"
    "|project_structure:id/INTEGER,project_id/INTEGER,family/TEXT,attachment_value/TEXT,attachment_kind/TEXT,entry_key/TEXT,payload/TEXT,created_at/TEXT,updated_at/TEXT"
    "|projects:id/INTEGER,slug/TEXT,name/TEXT,emoji/TEXT,default_branch/TEXT,github_repo/TEXT,public_item_prefix/TEXT,github_sync_mode/TEXT,created_at/TEXT,org_id/INTEGER,breakage_policy/TEXT"
    "|qa_artifacts:id/INTEGER,qa_run_id/INTEGER,artifact_type/TEXT,content_type/TEXT,artifact_handle/TEXT,metadata/TEXT,created_at/TEXT"
    "|qa_methods:id/TEXT,name/TEXT,description/TEXT,source_kind/TEXT,source_ref/TEXT,project_id/INTEGER,runner_id/TEXT,required_capability_kinds/TEXT,verdict_path/TEXT,verdict_contract/TEXT,evidence_contract/TEXT,success_policy_id/TEXT,success_policy_params/TEXT,concurrency_mode/TEXT,created_at/TEXT,updated_at/TEXT,display_icon/TEXT,display_order/INTEGER,display_group/TEXT,config_contract_id/TEXT,proof_kind/TEXT,runner_gloss/TEXT"
    "|qa_plan_cases:id/INTEGER,plan_id/INTEGER,case_key/TEXT,position/INTEGER,method_id/TEXT,instructions/TEXT,expected_outcome/TEXT,method_config/TEXT,success_policy_id/TEXT,success_policy_params/TEXT,host_baselines/TEXT,entry_surface/TEXT,required_completion/TEXT,created_at/TEXT,updated_at/TEXT"
    "|qa_plan_execution_results:execution_id/TEXT,ordinal/INTEGER,requirement_id/INTEGER,result_json/TEXT,completed_at/TEXT"
    "|qa_plan_executions:id/TEXT,item_id/INTEGER,deployment_run_id/TEXT,transition_id/TEXT,actor_id/TEXT,session_id/TEXT,roster_digest/TEXT,roster_json/TEXT,cursor_ordinal/INTEGER,state/TEXT,machine_lease_id/INTEGER,created_at/TEXT,heartbeat_at/TEXT,completed_at/TEXT,release_reason/TEXT,execution_target_json/TEXT,execution_target_digest/TEXT"
    "|qa_plan_item_attachments:item_id/INTEGER,transition_id/TEXT,qa_phase/TEXT,plan_id/INTEGER,attached_at/TEXT,attached_by_actor_id/INTEGER"
    "|qa_plan_project_defaults:project_id/INTEGER,workflow_id/TEXT,transition_id/TEXT,qa_phase/TEXT,plan_id/INTEGER,attached_at/TEXT,attached_by_actor_id/INTEGER"
    "|qa_plan_review_bundles:id/TEXT,execution_id/TEXT,roster_digest/TEXT,bundle_digest/TEXT,bundle_json/TEXT,state/TEXT,reviewer_actor_id/TEXT,reviewer_session_id/TEXT,created_at/TEXT,reviewed_at/TEXT"
    "|qa_plan_review_verdicts:bundle_id/TEXT,requirement_id/INTEGER,capture_run_id/INTEGER,review_run_id/INTEGER,verdict/TEXT,rationale/TEXT,decision_request_id/INTEGER,created_at/TEXT"
    "|qa_plans:id/INTEGER,project_id/INTEGER,slug/TEXT,name/TEXT,description/TEXT,success_policy_id/TEXT,success_policy_params/TEXT,created_at/TEXT,updated_at/TEXT,retired_at/TEXT,target_environment_id/INTEGER"
    "|qa_requirements:id/INTEGER,item_id/INTEGER,epic_id/INTEGER,task_num/INTEGER,deployment_run_id/TEXT,qa_kind/TEXT,qa_phase/TEXT,target_env/TEXT,blocking_mode/TEXT,requirement_source/TEXT,success_policy/TEXT,capability_requirements/TEXT,suite_id/TEXT,waived_at/TEXT,waiver_rationale/TEXT,waiver_source/TEXT,created_at/TEXT,plan_id/INTEGER,plan_case_key/TEXT,case_position/INTEGER,baseline_position/INTEGER,method_id/TEXT,method_name/TEXT,runner_id/TEXT,verdict_path/TEXT,host_baseline/TEXT,entry_surface/TEXT,required_completion/TEXT,workflow_transition_id/TEXT,instructions/TEXT,expected_outcome/TEXT,method_config/TEXT,execution_target_json/TEXT,execution_target_digest/TEXT"
    "|qa_runs:id/INTEGER,qa_requirement_id/INTEGER,performed_by/TEXT,qa_kind/TEXT,verdict/TEXT,verdict_reason/TEXT,execution_status/TEXT,score/REAL,confidence/REAL,raw_result/TEXT,duration_ms/INTEGER,started_at/TEXT,completed_at/TEXT,created_at/TEXT,case_outcome/TEXT,capture_degraded_reason/TEXT"
    "|release_entries:id/INTEGER,item_id/INTEGER,category/TEXT,title/TEXT,version/TEXT,project_id/INTEGER,created_at/TEXT"
    "|role_permissions:role_id/INTEGER,permission_id/INTEGER,created_at/TEXT"
    "|roles:id/INTEGER,name/TEXT,description/TEXT,created_at/TEXT"
    "|session_launch_attempts:attempt_id/TEXT,launch_id/TEXT,relay_id/TEXT,machine_id/TEXT,lease_id/TEXT,batch_id/TEXT,attempt_number/INTEGER,adapter_revision/TEXT,started_at/TEXT,completed_at/TEXT,native_session_id/TEXT,result_code/TEXT,evidence/TEXT"
    "|session_launches:launch_id/TEXT,requester_actor_id/INTEGER,requester_session_id/TEXT,project_id/INTEGER,requested_surface/TEXT,selected_surface/TEXT,requested_machine_id/TEXT,requested_model/TEXT,presentation_preference/TEXT,session_name/TEXT,allow_surface_fallback/INTEGER,message_id/TEXT,idempotency_key/TEXT,state/TEXT,assigned_relay_id/TEXT,assigned_machine_id/TEXT,native_session_id/TEXT,attestation_hash/TEXT,attestation_consumed_at/TEXT,registered_session_id/TEXT,deadline_at/TEXT,created_at/TEXT,assigned_at/TEXT,launching_at/TEXT,awaiting_registration_at/TEXT,completed_at/TEXT,result_code/TEXT,result_evidence/TEXT,origin/TEXT"
    "|session_message_attempts:attempt_id/TEXT,message_id/TEXT,target_session_id/TEXT,broker_session_id/TEXT,attempt_kind/TEXT,adapter_revision/TEXT,lease_id/TEXT,started_at/TEXT,completed_at/TEXT,result_code/TEXT,evidence/TEXT"
    "|session_message_recipients:message_id/TEXT,session_id/TEXT,project_id/INTEGER,resolution_evidence/TEXT,routing_snapshot/TEXT,executor_surface/TEXT,executor_version/TEXT,machine_id/TEXT,state/TEXT,created_at/TEXT,wake_after/TEXT,injection_lease_id/TEXT,injection_leased_at/TEXT,injection_lease_expires_at/TEXT,injection_count/INTEGER,last_injected_at/TEXT,acknowledged_at/TEXT,expired_at/TEXT,cancelled_at/TEXT,wake_attempt_count/INTEGER,last_wake_at/TEXT"
    "|session_messages:message_id/TEXT,sender_actor_id/INTEGER,sender_session_id/TEXT,body/TEXT,body_sha256/TEXT,selector_snapshot/TEXT,idempotency_key/TEXT,created_at/TEXT,expires_at/TEXT,cancelled_at/TEXT,cancelled_by_actor_id/INTEGER,cancellation_reason/TEXT"
    "|session_relays:relay_id/TEXT,actor_id/INTEGER,machine_id/TEXT,hostname/TEXT,relay_version/TEXT,surface_versions/TEXT,project_checkouts/TEXT,first_seen_at/TEXT,last_seen_at/TEXT,connected_until/TEXT,last_job_at/TEXT,state/TEXT,lease_id/TEXT,lease_expires_at/TEXT,surface_plan_limits/TEXT"
    "|session_surface_policies:mark_id/TEXT,machine_id/TEXT,surface/TEXT,state/TEXT,reason/TEXT,evidence/TEXT,set_by_actor_id/INTEGER,set_by_session_id/TEXT,created_at/TEXT,cleared_at/TEXT,cleared_by_actor_id/INTEGER"
    "|session_termination_reaps:target_session_id/TEXT,project_id/INTEGER,machine_id/TEXT,executor_surface/TEXT,target_native_thread_id/TEXT,launch_id/TEXT,state/TEXT,requested_at/TEXT,lease_id/TEXT,lease_expires_at/TEXT,completed_at/TEXT,result_code/TEXT,evidence/TEXT"
    "|session_tool_calls:id/INTEGER,session_id/TEXT,tool_use_id/TEXT,tool_name/TEXT,started_at/TEXT,completed_at/TEXT,outcome/TEXT,command_summary/TEXT"
    "|severity_config:id/INTEGER,event_name/TEXT,source_type/TEXT,min_severity/TEXT,created_at/TEXT"
    "|shepherd_verdicts:id/INTEGER,item/TEXT,transition/TEXT,worker/TEXT,verdict/TEXT,caveats/TEXT,attempt/INTEGER,created_at/TEXT"
    "|sites:id/INTEGER,project_id/INTEGER,name/TEXT,description/TEXT,created_at/TEXT,settings/TEXT"
    "|strategize_landed_carry:item_id/INTEGER,project_id/INTEGER,state/TEXT,first_seen_at/TEXT,last_updated_at/TEXT,last_session_id/TEXT,reason/TEXT"
    "|strategy_checkpoints:id/INTEGER,project_id/INTEGER,kind/TEXT,created_at/TEXT"
    "|strategy_doc_claims:id/INTEGER,project_id/INTEGER,strategy_doc_slug/TEXT,owner_kind/TEXT,owner_item_id/INTEGER,owner_session_id/TEXT,registered_by_actor_id/INTEGER,registered_by_session_id/TEXT,registered_at/TEXT,released_by_actor_id/INTEGER,released_by_session_id/TEXT,released_at/TEXT,release_mode/TEXT,release_reason/TEXT"
    "|strategy_doc_revisions:id/INTEGER,project_id/INTEGER,slug/TEXT,revision/INTEGER,content/TEXT,content_sha256/TEXT,byte_length/INTEGER,source_operation/TEXT,actor_id/INTEGER,created_at/TEXT,session_id/TEXT"
    "|strategy_docs:id/INTEGER,project_id/INTEGER,slug/TEXT,content/TEXT,updated_at/TEXT,updated_by_actor_id/INTEGER,archived_at/TEXT,parent_slug/TEXT"
    "|test_machine_verifications:project_id/INTEGER,capability_type/TEXT,status/TEXT,checked_at/TEXT,receipt_json/TEXT,error_code/TEXT,updated_at/TEXT"
    "|web_sessions:id/INTEGER,token_hash/TEXT,actor_id/INTEGER,created_at/TEXT,expires_at/TEXT,revoked_at/TEXT,last_used_at/TEXT"
    "|work_claims:id/INTEGER,session_id/TEXT,target_kind/TEXT,scope/TEXT,claim_type/TEXT,claimed_at/TEXT,last_heartbeat/TEXT,released_at/TEXT,release_reason/TEXT,reason/TEXT,reason_intent/TEXT,release_reason_intent/TEXT"
    "|workflow_execution_instruction_projects:instruction_id/INTEGER,project_id/INTEGER"
    "|workflow_execution_instruction_workflows:instruction_id/INTEGER,workflow_id/TEXT"
    "|workflow_execution_instructions:id/INTEGER,content/TEXT,applies_to_all_workflows/INTEGER,applies_to_all_projects/INTEGER,updated_by_actor_id/INTEGER,created_at/TEXT,updated_at/TEXT"
    "|workflow_versions:id/INTEGER,workflow_id/TEXT,version/INTEGER,definition_schema_version/INTEGER,definition_json/TEXT,definition_digest/TEXT,published_at/TEXT,published_by_actor_id/INTEGER,immutable_at/TEXT,derived_from_canon_version/INTEGER"
    "|workflows:id/TEXT,name/TEXT,description/TEXT,source/TEXT,status/TEXT,canon_follow/TEXT,canon_adopted_from_version/INTEGER,current_version_id/INTEGER,created_at/TEXT,updated_at/TEXT"
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
