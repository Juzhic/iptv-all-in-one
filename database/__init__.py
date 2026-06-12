# -*- coding: utf-8 -*-
"""
database 包 — IPTV 测速系统的数据库层。
统一导出 db.py 中的所有公共接口，外部模块可直接 from database import xxx。
"""
from database.db import (  # noqa: F401
    # 基础设施
    _get_conn,
    init_db,
    migrate_from_json,
    now_str,
    timestamp_str,
    DB_PATH,
    MAX_RUNS,
    CONFIG_DATA,
    LOCAL_TZ,
    DEFAULT_DEMO,
    DEFAULT_ALIAS,
    # 配置
    get_config_data,
    set_config_data,
    get_config,
    save_config,
    migrate_config_from_file,
    # 测速 run
    insert_run,
    get_latest_run,
    get_latest_passed_results,
    get_run_history,
    get_run_detail,
    delete_run,
    get_channel_summary,
    get_channel_summary_with_source,
    get_codec_stats,
    # 测速进度/日志
    clear_run_progress,
    update_run_progress,
    get_run_progress,
    insert_log,
    get_run_logs,
    # 调度器
    get_scheduler_state,
    update_scheduler_state,
    clear_scheduler_state,
    # 扫描 run
    insert_scan_run,
    update_scan_run,
    insert_scan_results,
    update_scan_result_stability,
    delete_scan_results_by_urls,
    get_scan_results,
    get_scan_run,
    get_scan_history,
    get_latest_scan_run,
    delete_scan_run,
    # 扫描进度/日志
    get_scan_progress,
    update_scan_progress,
    clear_scan_progress,
    insert_scan_log,
    get_scan_logs,
    clear_scan_logs,
    # 扫描统计
    get_scan_stats,
    # 持久化结果
    upsert_persistent_results,
    get_persistent_details_by_ip,
    get_all_persistent_for_detection_table,
    get_persistent_stats,
    get_persistent_grouped,
    get_persistent_by_url,
    update_persistent_check,
    delete_persistent_by_threshold,
    delete_persistent_by_id,
    get_persistent_for_test,
    get_all_persistent_for_check,
    get_pending_persistent,
    # 检测
    insert_detection_log,
    get_detection_logs,
    clear_detection_logs,
    insert_detection_run,
    finish_detection_run,
    insert_detection_results,
    get_detection_runs,
    get_detection_results,
    cleanup_old_detection_runs,
)
