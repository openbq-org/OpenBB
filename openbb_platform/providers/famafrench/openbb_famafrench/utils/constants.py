"""Constants for the Fama French datasets API."""

from typing import Any, Literal

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"

PERCENT_UNIT: dict[str, Any] = {"x-unit_measurement": "percent"}

DATASET_CHOICES = [
    {
        "label": "F-F Research Data Factors",
        "value": "F-F_Research_Data_Factors_CSV.zip",
    },
    {
        "label": "F-F Research Data Factors weekly",
        "value": "F-F_Research_Data_Factors_weekly_CSV.zip",
    },
    {
        "label": "F-F Research Data Factors daily",
        "value": "F-F_Research_Data_Factors_daily_CSV.zip",
    },
    {
        "label": "F-F Research Data 5 Factors 2x3",
        "value": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    },
    {
        "label": "F-F Research Data 5 Factors 2x3 daily",
        "value": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    },
    {"label": "Portfolios Formed on ME", "value": "Portfolios_Formed_on_ME_CSV.zip"},
    {
        "label": "Portfolios Formed on ME Wout Div",
        "value": "Portfolios_Formed_on_ME_Wout_Div_CSV.zip",
    },
    {
        "label": "Portfolios Formed on ME Daily",
        "value": "Portfolios_Formed_on_ME_Daily_CSV.zip",
    },
    {
        "label": "Portfolios Formed on BE-ME",
        "value": "Portfolios_Formed_on_BE-ME_CSV.zip",
    },
    {
        "label": "Portfolios Formed on BE-ME Wout Div",
        "value": "Portfolios_Formed_on_BE-ME_Wout_Div_CSV.zip",
    },
    {
        "label": "Portfolios Formed on BE-ME Daily",
        "value": "Portfolios_Formed_on_BE-ME_Daily_CSV.zip",
    },
    {"label": "Portfolios Formed on OP", "value": "Portfolios_Formed_on_OP_CSV.zip"},
    {
        "label": "Portfolios Formed on OP Wout Div",
        "value": "Portfolios_Formed_on_OP_Wout_Div_CSV.zip",
    },
    {
        "label": "Portfolios Formed on OP Daily",
        "value": "Portfolios_Formed_on_OP_Daily_CSV.zip",
    },
    {"label": "Portfolios Formed on INV", "value": "Portfolios_Formed_on_INV_CSV.zip"},
    {
        "label": "Portfolios Formed on INV Wout Div",
        "value": "Portfolios_Formed_on_INV_Wout_Div_CSV.zip",
    },
    {
        "label": "Portfolios Formed on INV Daily",
        "value": "Portfolios_Formed_on_INV_Daily_CSV.zip",
    },
    {"label": "6 Portfolios 2x3", "value": "6_Portfolios_2x3_CSV.zip"},
    {
        "label": "6 Portfolios 2x3 Wout Div",
        "value": "6_Portfolios_2x3_Wout_Div_CSV.zip",
    },
    {"label": "6 Portfolios 2x3 weekly", "value": "6_Portfolios_2x3_weekly_CSV.zip"},
    {"label": "6 Portfolios 2x3 daily", "value": "6_Portfolios_2x3_daily_CSV.zip"},
    {"label": "25 Portfolios 5x5", "value": "25_Portfolios_5x5_CSV.zip"},
    {
        "label": "25 Portfolios 5x5 Wout Div",
        "value": "25_Portfolios_5x5_Wout_Div_CSV.zip",
    },
    {"label": "25 Portfolios 5x5 Daily", "value": "25_Portfolios_5x5_Daily_CSV.zip"},
    {"label": "100 Portfolios 10x10", "value": "100_Portfolios_10x10_CSV.zip"},
    {
        "label": "100 Portfolios 10x10 Wout Div",
        "value": "100_Portfolios_10x10_Wout_Div_CSV.zip",
    },
    {
        "label": "100 Portfolios 10x10 Daily",
        "value": "100_Portfolios_10x10_Daily_CSV.zip",
    },
    {"label": "6 Portfolios ME OP 2x3", "value": "6_Portfolios_ME_OP_2x3_CSV.zip"},
    {
        "label": "6 Portfolios ME OP 2x3 Wout Div",
        "value": "6_Portfolios_ME_OP_2x3_Wout_Div_CSV.zip",
    },
    {
        "label": "6 Portfolios ME OP 2x3 daily",
        "value": "6_Portfolios_ME_OP_2x3_daily_CSV.zip",
    },
    {"label": "25 Portfolios ME OP 5x5", "value": "25_Portfolios_ME_OP_5x5_CSV.zip"},
    {
        "label": "25 Portfolios ME OP 5x5 Wout Div",
        "value": "25_Portfolios_ME_OP_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25 Portfolios ME OP 5x5 daily",
        "value": "25_Portfolios_ME_OP_5x5_daily_CSV.zip",
    },
    {
        "label": "100 Portfolios ME OP 10x10",
        "value": "100_Portfolios_ME_OP_10x10_CSV.zip",
    },
    {
        "label": "100 Portfolios 10x10 ME OP Wout Div",
        "value": "100_Portfolios_10x10_ME_OP_Wout_Div_CSV.zip",
    },
    {
        "label": "100 Portfolios ME OP 10x10 daily",
        "value": "100_Portfolios_ME_OP_10x10_daily_CSV.zip",
    },
    {"label": "6 Portfolios ME INV 2x3", "value": "6_Portfolios_ME_INV_2x3_CSV.zip"},
    {
        "label": "6 Portfolios ME INV 2x3 Wout Div",
        "value": "6_Portfolios_ME_INV_2x3_Wout_Div_CSV.zip",
    },
    {
        "label": "6 Portfolios ME INV 2x3 daily",
        "value": "6_Portfolios_ME_INV_2x3_daily_CSV.zip",
    },
    {"label": "25 Portfolios ME INV 5x5", "value": "25_Portfolios_ME_INV_5x5_CSV.zip"},
    {
        "label": "25 Portfolios ME INV 5x5 Wout Div",
        "value": "25_Portfolios_ME_INV_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25 Portfolios ME INV 5x5 daily",
        "value": "25_Portfolios_ME_INV_5x5_daily_CSV.zip",
    },
    {
        "label": "100 Portfolios ME INV 10x10",
        "value": "100_Portfolios_ME_INV_10x10_CSV.zip",
    },
    {
        "label": "100 Portfolios 10x10 ME INV Wout Div",
        "value": "100_Portfolios_10x10_ME_INV_Wout_Div_CSV.zip",
    },
    {
        "label": "100 Portfolios ME INV 10x10 daily",
        "value": "100_Portfolios_ME_INV_10x10_daily_CSV.zip",
    },
    {
        "label": "25 Portfolios BEME OP 5x5",
        "value": "25_Portfolios_BEME_OP_5x5_CSV.zip",
    },
    {
        "label": "25 Portfolios BEME OP 5x5 Wout Div",
        "value": "25_Portfolios_BEME_OP_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25 Portfolios BEME OP 5x5 daily",
        "value": "25_Portfolios_BEME_OP_5x5_daily_CSV.zip",
    },
    {
        "label": "25 Portfolios BEME INV 5x5",
        "value": "25_Portfolios_BEME_INV_5x5_CSV.zip",
    },
    {
        "label": "25 Portfolios BEME INV 5x5 Wout Div",
        "value": "25_Portfolios_BEME_INV_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25 Portfolios BEME INV 5x5 daily",
        "value": "25_Portfolios_BEME_INV_5x5_daily_CSV.zip",
    },
    {"label": "25 Portfolios OP INV 5x5", "value": "25_Portfolios_OP_INV_5x5_CSV.zip"},
    {
        "label": "25 Portfolios OP INV 5x5 Wout Div",
        "value": "25_Portfolios_OP_INV_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25 Portfolios OP INV 5x5 daily",
        "value": "25_Portfolios_OP_INV_5x5_daily_CSV.zip",
    },
    {
        "label": "32 Portfolios ME BEME OP 2x4x4",
        "value": "32_Portfolios_ME_BEME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "32 Portfolios ME BEME OP 2x4x4 Wout Div",
        "value": "32_Portfolios_ME_BEME_OP_2x4x4_Wout_Div_CSV.zip",
    },
    {
        "label": "32 Portfolios ME BEME INV 2x4x4",
        "value": "32_Portfolios_ME_BEME_INV_2x4x4_CSV.zip",
    },
    {
        "label": "32 Portfolios ME BEME INV 2x4x4 Wout Div",
        "value": "32_Portfolios_ME_BEME_INV_2x4x4_Wout_Div_CSV.zip",
    },
    {
        "label": "32 Portfolios ME OP INV 2x4x4",
        "value": "32_Portfolios_ME_OP_INV_2x4x4_CSV.zip",
    },
    {
        "label": "32 Portfolios ME OP INV 2x4x4 Wout Div",
        "value": "32_Portfolios_ME_OP_INV_2x4x4_Wout_Div_CSV.zip",
    },
    {"label": "Portfolios Formed on E-P", "value": "Portfolios_Formed_on_E-P_CSV.zip"},
    {
        "label": "Portfolios Formed on E-P Wout Div",
        "value": "Portfolios_Formed_on_E-P_Wout_Div_CSV.zip",
    },
    {
        "label": "Portfolios Formed on CF-P",
        "value": "Portfolios_Formed_on_CF-P_CSV.zip",
    },
    {
        "label": "Portfolios Formed on CF-P Wout Div",
        "value": "Portfolios_Formed_on_CF-P_Wout_Div_CSV.zip",
    },
    {"label": "Portfolios Formed on D-P", "value": "Portfolios_Formed_on_D-P_CSV.zip"},
    {
        "label": "Portfolios Formed on D-P Wout Div",
        "value": "Portfolios_Formed_on_D-P_Wout_Div_CSV.zip",
    },
    {"label": "6 Portfolios ME EP 2x3", "value": "6_Portfolios_ME_EP_2x3_CSV.zip"},
    {
        "label": "6 Portfolios ME EP 2x3 Wout Div",
        "value": "6_Portfolios_ME_EP_2x3_Wout_Div_CSV.zip",
    },
    {"label": "6 Portfolios ME CFP 2x3", "value": "6_Portfolios_ME_CFP_2x3_CSV.zip"},
    {
        "label": "6 Portfolios ME CFP 2x3 Wout Div",
        "value": "6_Portfolios_ME_CFP_2x3_Wout_Div_CSV.zip",
    },
    {"label": "6 Portfolios ME DP 2x3", "value": "6_Portfolios_ME_DP_2x3_CSV.zip"},
    {
        "label": "6 Portfolios ME DP 2x3 Wout Div",
        "value": "6_Portfolios_ME_DP_2x3_Wout_Div_CSV.zip",
    },
    {"label": "F-F Momentum Factor", "value": "F-F_Momentum_Factor_CSV.zip"},
    {
        "label": "F-F Momentum Factor daily",
        "value": "F-F_Momentum_Factor_daily_CSV.zip",
    },
    {
        "label": "6 Portfolios ME Prior 12 2",
        "value": "6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "6 Portfolios ME Prior 12 2 Daily",
        "value": "6_Portfolios_ME_Prior_12_2_Daily_CSV.zip",
    },
    {
        "label": "25 Portfolios ME Prior 12 2",
        "value": "25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "25 Portfolios ME Prior 12 2 Daily",
        "value": "25_Portfolios_ME_Prior_12_2_Daily_CSV.zip",
    },
    {"label": "10 Portfolios Prior 12 2", "value": "10_Portfolios_Prior_12_2_CSV.zip"},
    {
        "label": "10 Portfolios Prior 12 2 Daily",
        "value": "10_Portfolios_Prior_12_2_Daily_CSV.zip",
    },
    {"label": "F-F ST Reversal Factor", "value": "F-F_ST_Reversal_Factor_CSV.zip"},
    {
        "label": "F-F ST Reversal Factor daily",
        "value": "F-F_ST_Reversal_Factor_daily_CSV.zip",
    },
    {
        "label": "6 Portfolios ME Prior 1 0",
        "value": "6_Portfolios_ME_Prior_1_0_CSV.zip",
    },
    {
        "label": "6 Portfolios ME Prior 1 0 Daily",
        "value": "6_Portfolios_ME_Prior_1_0_Daily_CSV.zip",
    },
    {
        "label": "25 Portfolios ME Prior 1 0",
        "value": "25_Portfolios_ME_Prior_1_0_CSV.zip",
    },
    {
        "label": "25 Portfolios ME Prior 1 0 Daily",
        "value": "25_Portfolios_ME_Prior_1_0_Daily_CSV.zip",
    },
    {"label": "10 Portfolios Prior 1 0", "value": "10_Portfolios_Prior_1_0_CSV.zip"},
    {
        "label": "10 Portfolios Prior 1 0 Daily",
        "value": "10_Portfolios_Prior_1_0_Daily_CSV.zip",
    },
    {"label": "F-F LT Reversal Factor", "value": "F-F_LT_Reversal_Factor_CSV.zip"},
    {
        "label": "F-F LT Reversal Factor daily",
        "value": "F-F_LT_Reversal_Factor_daily_CSV.zip",
    },
    {
        "label": "6 Portfolios ME Prior 60 13",
        "value": "6_Portfolios_ME_Prior_60_13_CSV.zip",
    },
    {
        "label": "6 Portfolios ME Prior 60 13 Daily",
        "value": "6_Portfolios_ME_Prior_60_13_Daily_CSV.zip",
    },
    {
        "label": "25 Portfolios ME Prior 60 13",
        "value": "25_Portfolios_ME_Prior_60_13_CSV.zip",
    },
    {
        "label": "25 Portfolios ME Prior 60 13 Daily",
        "value": "25_Portfolios_ME_Prior_60_13_Daily_CSV.zip",
    },
    {
        "label": "10 Portfolios Prior 60 13",
        "value": "10_Portfolios_Prior_60_13_CSV.zip",
    },
    {
        "label": "10 Portfolios Prior 60 13 Daily",
        "value": "10_Portfolios_Prior_60_13_Daily_CSV.zip",
    },
    {"label": "Portfolios Formed on AC", "value": "Portfolios_Formed_on_AC_CSV.zip"},
    {"label": "25 Portfolios ME AC 5x5", "value": "25_Portfolios_ME_AC_5x5_CSV.zip"},
    {
        "label": "Portfolios Formed on BETA",
        "value": "Portfolios_Formed_on_BETA_CSV.zip",
    },
    {
        "label": "25 Portfolios ME BETA 5x5",
        "value": "25_Portfolios_ME_BETA_5x5_CSV.zip",
    },
    {"label": "Portfolios Formed on NI", "value": "Portfolios_Formed_on_NI_CSV.zip"},
    {"label": "25 Portfolios ME NI 5x5", "value": "25_Portfolios_ME_NI_5x5_CSV.zip"},
    {"label": "Portfolios Formed on VAR", "value": "Portfolios_Formed_on_VAR_CSV.zip"},
    {"label": "25 Portfolios ME VAR 5x5", "value": "25_Portfolios_ME_VAR_5x5_CSV.zip"},
    {
        "label": "Portfolios Formed on RESVAR",
        "value": "Portfolios_Formed_on_RESVAR_CSV.zip",
    },
    {
        "label": "25 Portfolios ME RESVAR 5x5",
        "value": "25_Portfolios_ME_RESVAR_5x5_CSV.zip",
    },
    {"label": "5 Industry Portfolios", "value": "5_Industry_Portfolios_CSV.zip"},
    {
        "label": "5 Industry Portfolios Wout Div",
        "value": "5_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "5 Industry Portfolios daily",
        "value": "5_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "10 Industry Portfolios", "value": "10_Industry_Portfolios_CSV.zip"},
    {
        "label": "10 Industry Portfolios Wout Div",
        "value": "10_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "10 Industry Portfolios daily",
        "value": "10_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "12 Industry Portfolios", "value": "12_Industry_Portfolios_CSV.zip"},
    {
        "label": "12 Industry Portfolios Wout Div",
        "value": "12_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "12 Industry Portfolios daily",
        "value": "12_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "17 Industry Portfolios", "value": "17_Industry_Portfolios_CSV.zip"},
    {
        "label": "17 Industry Portfolios Wout Div",
        "value": "17_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "17 Industry Portfolios daily",
        "value": "17_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "30 Industry Portfolios", "value": "30_Industry_Portfolios_CSV.zip"},
    {
        "label": "30 Industry Portfolios Wout Div",
        "value": "30_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "30 Industry Portfolios daily",
        "value": "30_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "38 Industry Portfolios", "value": "38_Industry_Portfolios_CSV.zip"},
    {
        "label": "38 Industry Portfolios Wout Div",
        "value": "38_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "38 Industry Portfolios daily",
        "value": "38_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "48 Industry Portfolios", "value": "48_Industry_Portfolios_CSV.zip"},
    {
        "label": "48 Industry Portfolios Wout Div",
        "value": "48_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "48 Industry Portfolios daily",
        "value": "48_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "49 Industry Portfolios", "value": "49_Industry_Portfolios_CSV.zip"},
    {
        "label": "49 Industry Portfolios Wout Div",
        "value": "49_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "49 Industry Portfolios daily",
        "value": "49_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "ME Breakpoints", "value": "ME_Breakpoints_CSV.zip"},
    {"label": "BE-ME Breakpoints", "value": "BE-ME_Breakpoints_CSV.zip"},
    {"label": "OP Breakpoints", "value": "OP_Breakpoints_CSV.zip"},
    {"label": "INV Breakpoints", "value": "INV_Breakpoints_CSV.zip"},
    {"label": "E-P Breakpoints", "value": "E-P_Breakpoints_CSV.zip"},
    {"label": "CF-P Breakpoints", "value": "CF-P_Breakpoints_CSV.zip"},
    {"label": "D-P Breakpoints", "value": "D-P_Breakpoints_CSV.zip"},
    {"label": "Prior 2-12 Breakpoints", "value": "Prior_2-12_Breakpoints_CSV.zip"},
    {"label": "Developed 3 Factors", "value": "Developed_3_Factors_CSV.zip"},
    {
        "label": "Developed 3 Factors Daily",
        "value": "Developed_3_Factors_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US 3 Factors",
        "value": "Developed_ex_US_3_Factors_CSV.zip",
    },
    {
        "label": "Developed ex US 3 Factors Daily",
        "value": "Developed_ex_US_3_Factors_Daily_CSV.zip",
    },
    {"label": "Europe 3 Factors", "value": "Europe_3_Factors_CSV.zip"},
    {"label": "Europe 3 Factors Daily", "value": "Europe_3_Factors_Daily_CSV.zip"},
    {"label": "Japan 3 Factors", "value": "Japan_3_Factors_CSV.zip"},
    {"label": "Japan 3 Factors Daily", "value": "Japan_3_Factors_Daily_CSV.zip"},
    {
        "label": "Asia Pacific ex Japan 3 Factors",
        "value": "Asia_Pacific_ex_Japan_3_Factors_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 3 Factors Daily",
        "value": "Asia_Pacific_ex_Japan_3_Factors_Daily_CSV.zip",
    },
    {"label": "North America 3 Factors", "value": "North_America_3_Factors_CSV.zip"},
    {
        "label": "North America 3 Factors Daily",
        "value": "North_America_3_Factors_Daily_CSV.zip",
    },
    {"label": "Developed 5 Factors", "value": "Developed_5_Factors_CSV.zip"},
    {
        "label": "Developed 5 Factors Daily",
        "value": "Developed_5_Factors_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US 5 Factors",
        "value": "Developed_ex_US_5_Factors_CSV.zip",
    },
    {
        "label": "Developed ex US 5 Factors Daily",
        "value": "Developed_ex_US_5_Factors_Daily_CSV.zip",
    },
    {"label": "Europe 5 Factors", "value": "Europe_5_Factors_CSV.zip"},
    {"label": "Europe 5 Factors Daily", "value": "Europe_5_Factors_Daily_CSV.zip"},
    {"label": "Japan 5 Factors", "value": "Japan_5_Factors_CSV.zip"},
    {"label": "Japan 5 Factors Daily", "value": "Japan_5_Factors_Daily_CSV.zip"},
    {
        "label": "Asia Pacific ex Japan 5 Factors",
        "value": "Asia_Pacific_ex_Japan_5_Factors_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 5 Factors Daily",
        "value": "Asia_Pacific_ex_Japan_5_Factors_Daily_CSV.zip",
    },
    {"label": "North America 5 Factors", "value": "North_America_5_Factors_CSV.zip"},
    {
        "label": "North America 5 Factors Daily",
        "value": "North_America_5_Factors_Daily_CSV.zip",
    },
    {"label": "Developed Mom Factor", "value": "Developed_Mom_Factor_CSV.zip"},
    {
        "label": "Developed Mom Factor Daily",
        "value": "Developed_Mom_Factor_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US Mom Factor",
        "value": "Developed_ex_US_Mom_Factor_CSV.zip",
    },
    {
        "label": "Developed ex US Mom Factor Daily",
        "value": "Developed_ex_US_Mom_Factor_Daily_CSV.zip",
    },
    {"label": "Europe Mom Factor", "value": "Europe_Mom_Factor_CSV.zip"},
    {"label": "Europe Mom Factor Daily", "value": "Europe_Mom_Factor_Daily_CSV.zip"},
    {"label": "Japan Mom Factor", "value": "Japan_Mom_Factor_CSV.zip"},
    {"label": "Japan Mom Factor Daily", "value": "Japan_Mom_Factor_Daily_CSV.zip"},
    {
        "label": "Asia Pacific ex Japan MOM Factor",
        "value": "Asia_Pacific_ex_Japan_MOM_Factor_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan MOM Factor Daily",
        "value": "Asia_Pacific_ex_Japan_MOM_Factor_Daily_CSV.zip",
    },
    {"label": "North America Mom Factor", "value": "North_America_Mom_Factor_CSV.zip"},
    {
        "label": "North America Mom Factor Daily",
        "value": "North_America_Mom_Factor_Daily_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME BE-ME",
        "value": "Developed_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME BE-ME daily",
        "value": "Developed_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME BE-ME",
        "value": "Developed_ex_US_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME BE-ME daily",
        "value": "Developed_ex_US_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME BE-ME",
        "value": "Europe_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME BE-ME daily",
        "value": "Europe_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Japan 6 Portfolios ME BE-ME",
        "value": "Japan_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Japan 6 Portfolios ME BE-ME daily",
        "value": "Japan_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME BE-ME",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME BE-ME daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME BE-ME",
        "value": "North_America_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME BE-ME daily",
        "value": "North_America_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME BE-ME",
        "value": "Developed_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME BE-ME daily",
        "value": "Developed_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME BE-ME",
        "value": "Developed_ex_US_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME BE-ME daily",
        "value": "Developed_ex_US_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME BE-ME",
        "value": "Europe_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME BE-ME daily",
        "value": "Europe_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME BE-ME",
        "value": "Japan_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME BE-ME daily",
        "value": "Japan_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME BE-ME",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME BE-ME daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME BE-ME",
        "value": "North_America_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME BE-ME daily",
        "value": "North_America_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME OP",
        "value": "Developed_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME OP Daily",
        "value": "Developed_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME OP",
        "value": "Developed_ex_US_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME OP Daily",
        "value": "Developed_ex_US_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME OP",
        "value": "Europe_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME OP Daily",
        "value": "Europe_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {"label": "Japan 6 Portfolios ME OP", "value": "Japan_6_Portfolios_ME_OP_CSV.zip"},
    {
        "label": "Japan 6 Portfolios ME OP Daily",
        "value": "Japan_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME OP",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME OP Daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME OP",
        "value": "North_America_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME OP Daily",
        "value": "North_America_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME OP",
        "value": "Developed_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME OP Daily",
        "value": "Developed_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME OP",
        "value": "Developed_ex_US_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME OP Daily",
        "value": "Developed_ex_US_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME OP",
        "value": "Europe_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME OP Daily",
        "value": "Europe_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME OP",
        "value": "Japan_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME OP Daily",
        "value": "Japan_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME OP",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME OP Daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME OP",
        "value": "North_America_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME OP Daily",
        "value": "North_America_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME INV",
        "value": "Developed_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME INV Daily",
        "value": "Developed_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME INV",
        "value": "Developed_ex_US_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME INV Daily",
        "value": "Developed_ex_US_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME INV",
        "value": "Europe_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME INV Daily",
        "value": "Europe_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Japan 6 Portfolios ME INV",
        "value": "Japan_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Japan 6 Portfolios ME INV Daily",
        "value": "Japan_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME INV",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME INV Daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME INV",
        "value": "North_America_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME INV Daily",
        "value": "North_America_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME INV",
        "value": "Developed_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME INV Daily",
        "value": "Developed_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME INV",
        "value": "Developed_ex_US_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME INV Daily",
        "value": "Developed_ex_US_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME INV",
        "value": "Europe_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME INV Daily",
        "value": "Europe_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME INV",
        "value": "Japan_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME INV Daily",
        "value": "Japan_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME INV",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME INV Daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME INV",
        "value": "North_America_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME INV Daily",
        "value": "North_America_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME Prior 12 2",
        "value": "Developed_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Developed 6 Portfolios ME Prior 250 20 daily",
        "value": "Developed_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME Prior 12 2",
        "value": "Developed_ex_US_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Developed ex US 6 Portfolios ME Prior 250 20 daily",
        "value": "Developed_ex_US_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME Prior 12 2",
        "value": "Europe_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Europe 6 Portfolios ME Prior 250 20 daily",
        "value": "Europe_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Japan 6 Portfolios ME Prior 12 2",
        "value": "Japan_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Japan 6 Portfolios ME Prior 250 20 daily",
        "value": "Japan_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME Prior 12 2",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 6 Portfolios ME Prior 250 20 daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME Prior 12 2",
        "value": "North_America_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "North America 6 Portfolios ME Prior 250 20 daily",
        "value": "North_America_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME Prior 12 2",
        "value": "Developed_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Developed 25 Portfolios ME Prior 250 20 daily",
        "value": "Developed_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME Prior 12 2",
        "value": "Developed_ex_US_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Developed ex US 25 Portfolios ME Prior 250 20 daily",
        "value": "Developed_ex_US_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME Prior 12 2",
        "value": "Europe_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Europe 25 Portfolios ME Prior 250 20 daily",
        "value": "Europe_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME Prior 12 2",
        "value": "Japan_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Japan 25 Portfolios ME Prior 250 20 daily",
        "value": "Japan_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME Prior 12 2",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 25 Portfolios ME Prior 250 20 daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME Prior 12 2",
        "value": "North_America_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "North America 25 Portfolios ME Prior 250 20 daily",
        "value": "North_America_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "Developed 32 Portfolios ME BE-ME OP 2x4x4",
        "value": "Developed_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Developed ex US 32 Portfolios ME BE-ME OP 2x4x4",
        "value": "Developed_ex_US_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Europe 32 Portfolios ME BE-ME OP 2x4x4",
        "value": "Europe_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Japan 32 Portfolios ME BE-ME OP 2x4x4",
        "value": "Japan_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 32 Portfolios ME BE-ME OP 2x4x4",
        "value": "Asia_Pacific_ex_Japan_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "North America 32 Portfolios ME BE-ME OP 2x4x4",
        "value": "North_America_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Developed 32 Portfolios ME BE-ME INV(TA) 2x4x4",
        "value": "Developed_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "Developed ex US 32 Portfolios ME BE-ME INV(TA) 2x4x4",
        "value": "Developed_ex_US_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "Europe 32 Portfolios ME BE-ME INV(TA) 2x4x4",
        "value": "Europe_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "Japan 32 Portfolios ME BE-ME INV(TA) 2x4x4",
        "value": "Japan_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 32 Portfolios ME BE-ME INV(TA) 2x4x4",
        "value": "Asia_Pacific_ex_Japan_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "North America 32 Portfolios ME BE-ME INV(TA) 2x4x4",
        "value": "North_America_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "Developed 32 Portfolios ME INV(TA) OP 2x4x4",
        "value": "Developed_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Developed ex US 32 Portfolios ME INV(TA) OP 2x4x4",
        "value": "Developed_ex_US_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Europe 32 Portfolios ME INV(TA) OP 2x4x4",
        "value": "Europe_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Japan 32 Portfolios ME INV(TA) OP 2x4x4",
        "value": "Japan_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "Asia Pacific ex Japan 32 Portfolios ME INV(TA) OP 2x4x4",
        "value": "Asia_Pacific_ex_Japan_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "North America 32 Portfolios ME INV(TA) OP 2x4x4",
        "value": "North_America_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {"label": "Emerging 5 Factors", "value": "Emerging_5_Factors_CSV.zip"},
    {"label": "Emerging MOM Factor", "value": "Emerging_MOM_Factor_CSV.zip"},
    {
        "label": "Emerging Markets 6 Portfolios ME BE-ME",
        "value": "Emerging_Markets_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "Emerging Markets 6 Portfolios ME OP",
        "value": "Emerging_Markets_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "Emerging Markets 6 Portfolios ME INV",
        "value": "Emerging_Markets_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "Emerging Markets 6 Portfolios ME Prior 12 2",
        "value": "Emerging_Markets_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "Emerging Markets 4 Portfolios BE-ME OP",
        "value": "Emerging_Markets_4_Portfolios_BE-ME_OP_CSV.zip",
    },
    {
        "label": "Emerging Markets 4 Portfolios OP INV",
        "value": "Emerging_Markets_4_Portfolios_OP_INV_CSV.zip",
    },
    {
        "label": "Emerging Markets 4 Portfolios BE-ME INV",
        "value": "Emerging_Markets_4_Portfolios_BE-ME_INV_CSV.zip",
    },
]


COUNTRY_PORTFOLIOS_URLS = {
    "dividends": "F-F_International_Countries.zip",
    "ex": "F-F_International_Countries_Wout_Div.zip",
}

COUNTRY_PORTFOLIO_FILES = {
    "Austria": "Austria.Dat",
    "Australia": "Austrlia.Dat",
    "Belgium": "Belgium.Dat",
    "Canada": "Canada.Dat",
    "Denmark": "Denmark.Dat",
    "Finland": "Finland.Dat",
    "France": "France.Dat",
    "Germany": "Germany.Dat",
    "Hong Kong": "HongKong.Dat",
    "Ireland": "Ireland.Dat",
    "Italy": "Italy.Dat",
    "Japan": "Japan.Dat",
    "Malaysia": "Malaysia.Dat",
    "Netherlands": "Nethrlnd.Dat",
    "New Zealand": "NewZland.Dat",
    "Norway": "Norway.Dat",
    "Singapore": "Singapor.Dat",
    "Spain": "Spain.Dat",
    "Sweden": "Sweden.Dat",
    "Switzerland": "Swtzrlnd.Dat",
    "United Kingdom": "UK.Dat",
}

CountryPortfolios = Literal[
    "austria",
    "australia",
    "belgium",
    "canada",
    "denmark",
    "finland",
    "france",
    "germany",
    "hong_kong",
    "ireland",
    "italy",
    "japan",
    "malaysia",
    "netherlands",
    "new_zealand",
    "norway",
    "singapore",
    "spain",
    "sweden",
    "switzerland",
    "united_kingdom",
]

INTERNATIONAL_INDEX_PORTFOLIOS_URLS = {
    "dividends": "F-F_International_Indices.zip",
    "ex": "F-F_International_Indices_Wout_Div.zip",
}

INTERNATIONAL_INDEX_PORTFOLIO_FILES = {
    "uk": "Ind_UK.Dat",
    "scandinavia": "Ind_Scandinavia.Dat",
    "europe": "Ind_Eur_With_UK.Dat",
    "europe_ex_uk": "Ind_Eur_WOut_UK.Dat",
    "asia_pacific": "Ind_Asia_Pacific.Dat",
    "all": "Ind_all.Dat",
}

InternationalIndexPortfolios = Literal[
    "uk",
    "scandinavia",
    "europe",
    "europe_ex_uk",
    "asia_pacific",
    "all",
]


REGIONS_MAP = {
    "america": "",
    "north_america": "North_America",
    "europe": "Europe",
    "japan": "Japan",
    "asia_pacific_ex_japan": "Asia_Pacific_ex_Japan",
    "developed": "Developed",
    "developed_ex_us": "Developed_ex_US",
    "emerging": "Emerging_Markets",
}


FACTOR_REGION_MAP: dict[str, Any] = {
    "america": {
        "factors": {
            "3_Factors": "F-F_Research_Data_Factors",
            "5_Factors": "F-F_Research_Data_5_Factors_2x3",
            "Momentum": "F-F_Momentum_Factor",
            "ST_Reversal": "F-F_ST_Reversal_Factor",
            "LT_Reversal": "F-F_LT_Reversal_Factor",
        },
        "intervals": {
            "3_Factors": {
                "daily": "_daily",
                "weekly": "_weekly",
                "monthly": "",
                "annual": "",
            },
            "5_Factors": {"daily": "_daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_daily", "monthly": ""},
            "ST_Reversal": {"daily": "_daily", "monthly": ""},
            "LT_Reversal": {"daily": "_daily", "monthly": ""},
        },
    },
    "north_america": {
        "factors": {
            "3_Factors": "North_America_3_Factors",
            "5_Factors": "North_America_5_Factors",
            "Momentum": "North_America_Mom_Factor",
        },
        "intervals": {
            "3_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "5_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_Daily", "monthly": "", "annual": ""},
        },
    },
    "europe": {
        "factors": {
            "3_Factors": "Europe_3_Factors",
            "5_Factors": "Europe_5_Factors",
            "Momentum": "Europe_Mom_Factor",
        },
        "intervals": {
            "3_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "5_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_Daily", "monthly": "", "annual": ""},
        },
    },
    "japan": {
        "factors": {
            "3_Factors": "Japan_3_Factors",
            "5_Factors": "Japan_5_Factors",
            "Momentum": "Japan_Mom_Factor",
        },
        "intervals": {
            "3_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "5_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_Daily", "monthly": "", "annual": ""},
        },
    },
    "asia_pacific_ex_japan": {
        "factors": {
            "3_Factors": "Asia_Pacific_ex_Japan_3_Factors",
            "5_Factors": "Asia_Pacific_ex_Japan_5_Factors",
            "Momentum": "Asia_Pacific_ex_Japan_MOM_Factor",
        },
        "intervals": {
            "3_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "5_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_Daily", "monthly": "", "annual": ""},
        },
    },
    "developed": {
        "factors": {
            "3_Factors": "Developed_3_Factors",
            "5_Factors": "Developed_5_Factors",
            "Momentum": "Developed_Mom_Factor",
        },
        "intervals": {
            "3_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "5_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_Daily", "monthly": "", "annual": ""},
        },
    },
    "developed_ex_us": {
        "factors": {
            "3_Factors": "Developed_ex_US_3_Factors",
            "5_Factors": "Developed_ex_US_5_Factors",
            "Momentum": "Developed_ex_US_Mom_Factor",
        },
        "intervals": {
            "3_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "5_Factors": {"daily": "_Daily", "monthly": "", "annual": ""},
            "Momentum": {"daily": "_Daily", "monthly": "", "annual": ""},
        },
    },
    "emerging": {
        "factors": {
            "5_Factors": "Emerging_5_Factors",
            "Momentum": "Emerging_MOM_Factor",
        },
        "intervals": {
            "5_Factors": {"monthly": "", "annual": ""},
            "Momentum": {"monthly": "", "annual": ""},
        },
    },
}

USPortfolios = Literal[
    "portfolios_formed_on_me",
    "portfolios_formed_on_me_wout_div",
    "portfolios_formed_on_me_daily",
    "portfolios_formed_on_be-me",
    "portfolios_formed_on_be-me_wout_div",
    "portfolios_formed_on_be-me_daily",
    "portfolios_formed_on_op",
    "portfolios_formed_on_op_wout_div",
    "portfolios_formed_on_op_daily",
    "portfolios_formed_on_inv",
    "portfolios_formed_on_inv_wout_div",
    "portfolios_formed_on_inv_daily",
    "6_portfolios_2x3",
    "6_portfolios_2x3_wout_div",
    "6_portfolios_2x3_weekly",
    "6_portfolios_2x3_daily",
    "25_portfolios_5x5",
    "25_portfolios_5x5_wout_div",
    "25_portfolios_5x5_daily",
    "100_portfolios_10x10",
    "100_portfolios_10x10_wout_div",
    "100_portfolios_10x10_daily",
    "6_portfolios_me_op_2x3",
    "6_portfolios_me_op_2x3_wout_div",
    "6_portfolios_me_op_2x3_daily",
    "25_portfolios_me_op_5x5",
    "25_portfolios_me_op_5x5_wout_div",
    "25_portfolios_me_op_5x5_daily",
    "100_portfolios_me_op_10x10",
    "100_portfolios_10x10_me_op_wout_div",
    "100_portfolios_me_op_10x10_daily",
    "6_portfolios_me_inv_2x3",
    "6_portfolios_me_inv_2x3_wout_div",
    "6_portfolios_me_inv_2x3_daily",
    "25_portfolios_me_inv_5x5",
    "25_portfolios_me_inv_5x5_wout_div",
    "25_portfolios_me_inv_5x5_daily",
    "100_portfolios_me_inv_10x10",
    "100_portfolios_10x10_me_inv_wout_div",
    "100_portfolios_me_inv_10x10_daily",
    "25_portfolios_beme_op_5x5",
    "25_portfolios_beme_op_5x5_wout_div",
    "25_portfolios_beme_op_5x5_daily",
    "25_portfolios_beme_inv_5x5",
    "25_portfolios_beme_inv_5x5_wout_div",
    "25_portfolios_beme_inv_5x5_daily",
    "25_portfolios_op_inv_5x5",
    "25_portfolios_op_inv_5x5_wout_div",
    "25_portfolios_op_inv_5x5_daily",
    "32_portfolios_me_beme_op_2x4x4",
    "32_portfolios_me_beme_op_2x4x4_wout_div",
    "32_portfolios_me_beme_inv_2x4x4",
    "32_portfolios_me_beme_inv_2x4x4_wout_div",
    "32_portfolios_me_op_inv_2x4x4",
    "32_portfolios_me_op_inv_2x4x4_wout_div",
    "portfolios_formed_on_e-p",
    "portfolios_formed_on_e-p_wout_div",
    "portfolios_formed_on_cf-p",
    "portfolios_formed_on_cf-p_wout_div",
    "portfolios_formed_on_d-p",
    "portfolios_formed_on_d-p_wout_div",
    "6_portfolios_me_ep_2x3",
    "6_portfolios_me_ep_2x3_wout_div",
    "6_portfolios_me_cfp_2x3",
    "6_portfolios_me_cfp_2x3_wout_div",
    "6_portfolios_me_dp_2x3",
    "6_portfolios_me_dp_2x3_wout_div",
    "6_portfolios_me_prior_12_2",
    "6_portfolios_me_prior_12_2_daily",
    "25_portfolios_me_prior_12_2",
    "25_portfolios_me_prior_12_2_daily",
    "10_portfolios_prior_12_2",
    "10_portfolios_prior_12_2_daily",
    "6_portfolios_me_prior_1_0",
    "6_portfolios_me_prior_1_0_daily",
    "25_portfolios_me_prior_1_0",
    "25_portfolios_me_prior_1_0_daily",
    "10_portfolios_prior_1_0",
    "10_portfolios_prior_1_0_daily",
    "6_portfolios_me_prior_60_13",
    "6_portfolios_me_prior_60_13_daily",
    "25_portfolios_me_prior_60_13",
    "25_portfolios_me_prior_60_13_daily",
    "10_portfolios_prior_60_13",
    "10_portfolios_prior_60_13_daily",
    "portfolios_formed_on_ac",
    "25_portfolios_me_ac_5x5",
    "portfolios_formed_on_beta",
    "25_portfolios_me_beta_5x5",
    "portfolios_formed_on_ni",
    "25_portfolios_me_ni_5x5",
    "portfolios_formed_on_var",
    "25_portfolios_me_var_5x5",
    "portfolios_formed_on_resvar",
    "25_portfolios_me_resvar_5x5",
    "5_industry_portfolios",
    "5_industry_portfolios_wout_div",
    "5_industry_portfolios_daily",
    "10_industry_portfolios",
    "10_industry_portfolios_wout_div",
    "10_industry_portfolios_daily",
    "12_industry_portfolios",
    "12_industry_portfolios_wout_div",
    "12_industry_portfolios_daily",
    "17_industry_portfolios",
    "17_industry_portfolios_wout_div",
    "17_industry_portfolios_daily",
    "30_industry_portfolios",
    "30_industry_portfolios_wout_div",
    "30_industry_portfolios_daily",
    "38_industry_portfolios",
    "38_industry_portfolios_wout_div",
    "38_industry_portfolios_daily",
    "48_industry_portfolios",
    "48_industry_portfolios_wout_div",
    "48_industry_portfolios_daily",
    "49_industry_portfolios",
    "49_industry_portfolios_wout_div",
    "49_industry_portfolios_daily",
]


portfolio_choices = [
    {"label": "portfolios_formed_on_me", "value": "Portfolios_Formed_on_ME_CSV.zip"},
    {
        "label": "portfolios_formed_on_me_wout_div",
        "value": "Portfolios_Formed_on_ME_Wout_Div_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_me_daily",
        "value": "Portfolios_Formed_on_ME_Daily_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_be-me",
        "value": "Portfolios_Formed_on_BE-ME_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_be-me_wout_div",
        "value": "Portfolios_Formed_on_BE-ME_Wout_Div_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_be-me_daily",
        "value": "Portfolios_Formed_on_BE-ME_Daily_CSV.zip",
    },
    {"label": "portfolios_formed_on_op", "value": "Portfolios_Formed_on_OP_CSV.zip"},
    {
        "label": "portfolios_formed_on_op_wout_div",
        "value": "Portfolios_Formed_on_OP_Wout_Div_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_op_daily",
        "value": "Portfolios_Formed_on_OP_Daily_CSV.zip",
    },
    {"label": "portfolios_formed_on_inv", "value": "Portfolios_Formed_on_INV_CSV.zip"},
    {
        "label": "portfolios_formed_on_inv_wout_div",
        "value": "Portfolios_Formed_on_INV_Wout_Div_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_inv_daily",
        "value": "Portfolios_Formed_on_INV_Daily_CSV.zip",
    },
    {"label": "6_portfolios_2x3", "value": "6_Portfolios_2x3_CSV.zip"},
    {
        "label": "6_portfolios_2x3_wout_div",
        "value": "6_Portfolios_2x3_Wout_Div_CSV.zip",
    },
    {"label": "6_portfolios_2x3_weekly", "value": "6_Portfolios_2x3_weekly_CSV.zip"},
    {"label": "6_portfolios_2x3_daily", "value": "6_Portfolios_2x3_daily_CSV.zip"},
    {"label": "25_portfolios_5x5", "value": "25_Portfolios_5x5_CSV.zip"},
    {
        "label": "25_portfolios_5x5_wout_div",
        "value": "25_Portfolios_5x5_Wout_Div_CSV.zip",
    },
    {"label": "25_portfolios_5x5_daily", "value": "25_Portfolios_5x5_Daily_CSV.zip"},
    {"label": "100_portfolios_10x10", "value": "100_Portfolios_10x10_CSV.zip"},
    {
        "label": "100_portfolios_10x10_wout_div",
        "value": "100_Portfolios_10x10_Wout_Div_CSV.zip",
    },
    {
        "label": "100_portfolios_10x10_daily",
        "value": "100_Portfolios_10x10_Daily_CSV.zip",
    },
    {"label": "6_portfolios_me_op_2x3", "value": "6_Portfolios_ME_OP_2x3_CSV.zip"},
    {
        "label": "6_portfolios_me_op_2x3_wout_div",
        "value": "6_Portfolios_ME_OP_2x3_Wout_Div_CSV.zip",
    },
    {
        "label": "6_portfolios_me_op_2x3_daily",
        "value": "6_Portfolios_ME_OP_2x3_daily_CSV.zip",
    },
    {"label": "25_portfolios_me_op_5x5", "value": "25_Portfolios_ME_OP_5x5_CSV.zip"},
    {
        "label": "25_portfolios_me_op_5x5_wout_div",
        "value": "25_Portfolios_ME_OP_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25_portfolios_me_op_5x5_daily",
        "value": "25_Portfolios_ME_OP_5x5_daily_CSV.zip",
    },
    {
        "label": "100_portfolios_me_op_10x10",
        "value": "100_Portfolios_ME_OP_10x10_CSV.zip",
    },
    {
        "label": "100_portfolios_10x10_me_op_wout_div",
        "value": "100_Portfolios_10x10_ME_OP_Wout_Div_CSV.zip",
    },
    {
        "label": "100_portfolios_me_op_10x10_daily",
        "value": "100_Portfolios_ME_OP_10x10_daily_CSV.zip",
    },
    {"label": "6_portfolios_me_inv_2x3", "value": "6_Portfolios_ME_INV_2x3_CSV.zip"},
    {
        "label": "6_portfolios_me_inv_2x3_wout_div",
        "value": "6_Portfolios_ME_INV_2x3_Wout_Div_CSV.zip",
    },
    {
        "label": "6_portfolios_me_inv_2x3_daily",
        "value": "6_Portfolios_ME_INV_2x3_daily_CSV.zip",
    },
    {"label": "25_portfolios_me_inv_5x5", "value": "25_Portfolios_ME_INV_5x5_CSV.zip"},
    {
        "label": "25_portfolios_me_inv_5x5_wout_div",
        "value": "25_Portfolios_ME_INV_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25_portfolios_me_inv_5x5_daily",
        "value": "25_Portfolios_ME_INV_5x5_daily_CSV.zip",
    },
    {
        "label": "100_portfolios_me_inv_10x10",
        "value": "100_Portfolios_ME_INV_10x10_CSV.zip",
    },
    {
        "label": "100_portfolios_10x10_me_inv_wout_div",
        "value": "100_Portfolios_10x10_ME_INV_Wout_Div_CSV.zip",
    },
    {
        "label": "100_portfolios_me_inv_10x10_daily",
        "value": "100_Portfolios_ME_INV_10x10_daily_CSV.zip",
    },
    {
        "label": "25_portfolios_beme_op_5x5",
        "value": "25_Portfolios_BEME_OP_5x5_CSV.zip",
    },
    {
        "label": "25_portfolios_beme_op_5x5_wout_div",
        "value": "25_Portfolios_BEME_OP_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25_portfolios_beme_op_5x5_daily",
        "value": "25_Portfolios_BEME_OP_5x5_daily_CSV.zip",
    },
    {
        "label": "25_portfolios_beme_inv_5x5",
        "value": "25_Portfolios_BEME_INV_5x5_CSV.zip",
    },
    {
        "label": "25_portfolios_beme_inv_5x5_wout_div",
        "value": "25_Portfolios_BEME_INV_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25_portfolios_beme_inv_5x5_daily",
        "value": "25_Portfolios_BEME_INV_5x5_daily_CSV.zip",
    },
    {"label": "25_portfolios_op_inv_5x5", "value": "25_Portfolios_OP_INV_5x5_CSV.zip"},
    {
        "label": "25_portfolios_op_inv_5x5_wout_div",
        "value": "25_Portfolios_OP_INV_5x5_Wout_Div_CSV.zip",
    },
    {
        "label": "25_portfolios_op_inv_5x5_daily",
        "value": "25_Portfolios_OP_INV_5x5_daily_CSV.zip",
    },
    {
        "label": "32_portfolios_me_beme_op_2x4x4",
        "value": "32_Portfolios_ME_BEME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "32_portfolios_me_beme_op_2x4x4_wout_div",
        "value": "32_Portfolios_ME_BEME_OP_2x4x4_Wout_Div_CSV.zip",
    },
    {
        "label": "32_portfolios_me_beme_inv_2x4x4",
        "value": "32_Portfolios_ME_BEME_INV_2x4x4_CSV.zip",
    },
    {
        "label": "32_portfolios_me_beme_inv_2x4x4_wout_div",
        "value": "32_Portfolios_ME_BEME_INV_2x4x4_Wout_Div_CSV.zip",
    },
    {
        "label": "32_portfolios_me_op_inv_2x4x4",
        "value": "32_Portfolios_ME_OP_INV_2x4x4_CSV.zip",
    },
    {
        "label": "32_portfolios_me_op_inv_2x4x4_wout_div",
        "value": "32_Portfolios_ME_OP_INV_2x4x4_Wout_Div_CSV.zip",
    },
    {"label": "portfolios_formed_on_e-p", "value": "Portfolios_Formed_on_E-P_CSV.zip"},
    {
        "label": "portfolios_formed_on_e-p_wout_div",
        "value": "Portfolios_Formed_on_E-P_Wout_Div_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_cf-p",
        "value": "Portfolios_Formed_on_CF-P_CSV.zip",
    },
    {
        "label": "portfolios_formed_on_cf-p_wout_div",
        "value": "Portfolios_Formed_on_CF-P_Wout_Div_CSV.zip",
    },
    {"label": "portfolios_formed_on_d-p", "value": "Portfolios_Formed_on_D-P_CSV.zip"},
    {
        "label": "portfolios_formed_on_d-p_wout_div",
        "value": "Portfolios_Formed_on_D-P_Wout_Div_CSV.zip",
    },
    {"label": "6_portfolios_me_ep_2x3", "value": "6_Portfolios_ME_EP_2x3_CSV.zip"},
    {
        "label": "6_portfolios_me_ep_2x3_wout_div",
        "value": "6_Portfolios_ME_EP_2x3_Wout_Div_CSV.zip",
    },
    {"label": "6_portfolios_me_cfp_2x3", "value": "6_Portfolios_ME_CFP_2x3_CSV.zip"},
    {
        "label": "6_portfolios_me_cfp_2x3_wout_div",
        "value": "6_Portfolios_ME_CFP_2x3_Wout_Div_CSV.zip",
    },
    {"label": "6_portfolios_me_dp_2x3", "value": "6_Portfolios_ME_DP_2x3_CSV.zip"},
    {
        "label": "6_portfolios_me_dp_2x3_wout_div",
        "value": "6_Portfolios_ME_DP_2x3_Wout_Div_CSV.zip",
    },
    {
        "label": "6_portfolios_me_prior_12_2",
        "value": "6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "6_portfolios_me_prior_12_2_daily",
        "value": "6_Portfolios_ME_Prior_12_2_Daily_CSV.zip",
    },
    {
        "label": "25_portfolios_me_prior_12_2",
        "value": "25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "25_portfolios_me_prior_12_2_daily",
        "value": "25_Portfolios_ME_Prior_12_2_Daily_CSV.zip",
    },
    {"label": "10_portfolios_prior_12_2", "value": "10_Portfolios_Prior_12_2_CSV.zip"},
    {
        "label": "10_portfolios_prior_12_2_daily",
        "value": "10_Portfolios_Prior_12_2_Daily_CSV.zip",
    },
    {
        "label": "6_portfolios_me_prior_1_0",
        "value": "6_Portfolios_ME_Prior_1_0_CSV.zip",
    },
    {
        "label": "6_portfolios_me_prior_1_0_daily",
        "value": "6_Portfolios_ME_Prior_1_0_Daily_CSV.zip",
    },
    {
        "label": "25_portfolios_me_prior_1_0",
        "value": "25_Portfolios_ME_Prior_1_0_CSV.zip",
    },
    {
        "label": "25_portfolios_me_prior_1_0_daily",
        "value": "25_Portfolios_ME_Prior_1_0_Daily_CSV.zip",
    },
    {"label": "10_portfolios_prior_1_0", "value": "10_Portfolios_Prior_1_0_CSV.zip"},
    {
        "label": "10_portfolios_prior_1_0_daily",
        "value": "10_Portfolios_Prior_1_0_Daily_CSV.zip",
    },
    {
        "label": "6_portfolios_me_prior_60_13",
        "value": "6_Portfolios_ME_Prior_60_13_CSV.zip",
    },
    {
        "label": "6_portfolios_me_prior_60_13_daily",
        "value": "6_Portfolios_ME_Prior_60_13_Daily_CSV.zip",
    },
    {
        "label": "25_portfolios_me_prior_60_13",
        "value": "25_Portfolios_ME_Prior_60_13_CSV.zip",
    },
    {
        "label": "25_portfolios_me_prior_60_13_daily",
        "value": "25_Portfolios_ME_Prior_60_13_Daily_CSV.zip",
    },
    {
        "label": "10_portfolios_prior_60_13",
        "value": "10_Portfolios_Prior_60_13_CSV.zip",
    },
    {
        "label": "10_portfolios_prior_60_13_daily",
        "value": "10_Portfolios_Prior_60_13_Daily_CSV.zip",
    },
    {"label": "portfolios_formed_on_ac", "value": "Portfolios_Formed_on_AC_CSV.zip"},
    {"label": "25_portfolios_me_ac_5x5", "value": "25_Portfolios_ME_AC_5x5_CSV.zip"},
    {
        "label": "portfolios_formed_on_beta",
        "value": "Portfolios_Formed_on_BETA_CSV.zip",
    },
    {
        "label": "25_portfolios_me_beta_5x5",
        "value": "25_Portfolios_ME_BETA_5x5_CSV.zip",
    },
    {"label": "portfolios_formed_on_ni", "value": "Portfolios_Formed_on_NI_CSV.zip"},
    {"label": "25_portfolios_me_ni_5x5", "value": "25_Portfolios_ME_NI_5x5_CSV.zip"},
    {"label": "portfolios_formed_on_var", "value": "Portfolios_Formed_on_VAR_CSV.zip"},
    {"label": "25_portfolios_me_var_5x5", "value": "25_Portfolios_ME_VAR_5x5_CSV.zip"},
    {
        "label": "portfolios_formed_on_resvar",
        "value": "Portfolios_Formed_on_RESVAR_CSV.zip",
    },
    {
        "label": "25_portfolios_me_resvar_5x5",
        "value": "25_Portfolios_ME_RESVAR_5x5_CSV.zip",
    },
    {"label": "5_industry_portfolios", "value": "5_Industry_Portfolios_CSV.zip"},
    {
        "label": "5_industry_portfolios_wout_div",
        "value": "5_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "5_industry_portfolios_daily",
        "value": "5_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "10_industry_portfolios", "value": "10_Industry_Portfolios_CSV.zip"},
    {
        "label": "10_industry_portfolios_wout_div",
        "value": "10_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "10_industry_portfolios_daily",
        "value": "10_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "12_industry_portfolios", "value": "12_Industry_Portfolios_CSV.zip"},
    {
        "label": "12_industry_portfolios_wout_div",
        "value": "12_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "12_industry_portfolios_daily",
        "value": "12_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "17_industry_portfolios", "value": "17_Industry_Portfolios_CSV.zip"},
    {
        "label": "17_industry_portfolios_wout_div",
        "value": "17_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "17_industry_portfolios_daily",
        "value": "17_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "30_industry_portfolios", "value": "30_Industry_Portfolios_CSV.zip"},
    {
        "label": "30_industry_portfolios_wout_div",
        "value": "30_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "30_industry_portfolios_daily",
        "value": "30_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "38_industry_portfolios", "value": "38_Industry_Portfolios_CSV.zip"},
    {
        "label": "38_industry_portfolios_wout_div",
        "value": "38_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "38_industry_portfolios_daily",
        "value": "38_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "48_industry_portfolios", "value": "48_Industry_Portfolios_CSV.zip"},
    {
        "label": "48_industry_portfolios_wout_div",
        "value": "48_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "48_industry_portfolios_daily",
        "value": "48_Industry_Portfolios_daily_CSV.zip",
    },
    {"label": "49_industry_portfolios", "value": "49_Industry_Portfolios_CSV.zip"},
    {
        "label": "49_industry_portfolios_wout_div",
        "value": "49_Industry_Portfolios_Wout_Div_CSV.zip",
    },
    {
        "label": "49_industry_portfolios_daily",
        "value": "49_Industry_Portfolios_daily_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_be-me",
        "value": "Developed_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_be-me_daily",
        "value": "Developed_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_be-me",
        "value": "Developed_ex_US_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_be-me_daily",
        "value": "Developed_ex_US_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_be-me",
        "value": "Europe_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_be-me_daily",
        "value": "Europe_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "japan_6_portfolios_me_be-me",
        "value": "Japan_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "japan_6_portfolios_me_be-me_daily",
        "value": "Japan_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_be-me",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_be-me_daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_be-me",
        "value": "North_America_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_be-me_daily",
        "value": "North_America_6_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_be-me",
        "value": "Developed_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_be-me_daily",
        "value": "Developed_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_be-me",
        "value": "Developed_ex_US_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_be-me_daily",
        "value": "Developed_ex_US_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_be-me",
        "value": "Europe_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_be-me_daily",
        "value": "Europe_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_be-me",
        "value": "Japan_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_be-me_daily",
        "value": "Japan_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_be-me",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_be-me_daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_be-me",
        "value": "North_America_25_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_be-me_daily",
        "value": "North_America_25_Portfolios_ME_BE-ME_daily_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_op",
        "value": "Developed_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_op_daily",
        "value": "Developed_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_op",
        "value": "Developed_ex_US_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_op_daily",
        "value": "Developed_ex_US_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_op",
        "value": "Europe_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_op_daily",
        "value": "Europe_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {"label": "japan_6_portfolios_me_op", "value": "Japan_6_Portfolios_ME_OP_CSV.zip"},
    {
        "label": "japan_6_portfolios_me_op_daily",
        "value": "Japan_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_op",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_op_daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_op",
        "value": "North_America_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_op_daily",
        "value": "North_America_6_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_op",
        "value": "Developed_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_op_daily",
        "value": "Developed_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_op",
        "value": "Developed_ex_US_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_op_daily",
        "value": "Developed_ex_US_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_op",
        "value": "Europe_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_op_daily",
        "value": "Europe_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_op",
        "value": "Japan_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_op_daily",
        "value": "Japan_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_op",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_op_daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_op",
        "value": "North_America_25_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_op_daily",
        "value": "North_America_25_Portfolios_ME_OP_Daily_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_inv",
        "value": "Developed_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_inv_daily",
        "value": "Developed_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_inv",
        "value": "Developed_ex_US_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_inv_daily",
        "value": "Developed_ex_US_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_inv",
        "value": "Europe_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_inv_daily",
        "value": "Europe_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "japan_6_portfolios_me_inv",
        "value": "Japan_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "japan_6_portfolios_me_inv_daily",
        "value": "Japan_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_inv",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_inv_daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_inv",
        "value": "North_America_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_inv_daily",
        "value": "North_America_6_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_inv",
        "value": "Developed_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_inv_daily",
        "value": "Developed_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_inv",
        "value": "Developed_ex_US_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_inv_daily",
        "value": "Developed_ex_US_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_inv",
        "value": "Europe_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_inv_daily",
        "value": "Europe_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_inv",
        "value": "Japan_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_inv_daily",
        "value": "Japan_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_inv",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_inv_daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_inv",
        "value": "North_America_25_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_inv_daily",
        "value": "North_America_25_Portfolios_ME_INV_Daily_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_prior_12_2",
        "value": "Developed_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "developed_6_portfolios_me_prior_250_20_daily",
        "value": "Developed_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_prior_12_2",
        "value": "Developed_ex_US_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "developed_ex_us_6_portfolios_me_prior_250_20_daily",
        "value": "Developed_ex_US_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_prior_12_2",
        "value": "Europe_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "europe_6_portfolios_me_prior_250_20_daily",
        "value": "Europe_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "japan_6_portfolios_me_prior_12_2",
        "value": "Japan_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "japan_6_portfolios_me_prior_250_20_daily",
        "value": "Japan_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_prior_12_2",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_6_portfolios_me_prior_250_20_daily",
        "value": "Asia_Pacific_ex_Japan_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_prior_12_2",
        "value": "North_America_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "north_america_6_portfolios_me_prior_250_20_daily",
        "value": "North_America_6_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_prior_12_2",
        "value": "Developed_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "developed_25_portfolios_me_prior_250_20_daily",
        "value": "Developed_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_prior_12_2",
        "value": "Developed_ex_US_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "developed_ex_us_25_portfolios_me_prior_250_20_daily",
        "value": "Developed_ex_US_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_prior_12_2",
        "value": "Europe_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "europe_25_portfolios_me_prior_250_20_daily",
        "value": "Europe_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_prior_12_2",
        "value": "Japan_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "japan_25_portfolios_me_prior_250_20_daily",
        "value": "Japan_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_prior_12_2",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_25_portfolios_me_prior_250_20_daily",
        "value": "Asia_Pacific_ex_Japan_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_prior_12_2",
        "value": "North_America_25_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "north_america_25_portfolios_me_prior_250_20_daily",
        "value": "North_America_25_Portfolios_ME_Prior_250_20_daily_CSV.zip",
    },
    {
        "label": "developed_32_portfolios_me_be-me_op_2x4x4",
        "value": "Developed_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "developed_ex_us_32_portfolios_me_be-me_op_2x4x4",
        "value": "Developed_ex_US_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "europe_32_portfolios_me_be-me_op_2x4x4",
        "value": "Europe_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "japan_32_portfolios_me_be-me_op_2x4x4",
        "value": "Japan_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_32_portfolios_me_be-me_op_2x4x4",
        "value": "Asia_Pacific_ex_Japan_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "north_america_32_portfolios_me_be-me_op_2x4x4",
        "value": "North_America_32_Portfolios_ME_BE-ME_OP_2x4x4_CSV.zip",
    },
    {
        "label": "developed_32_portfolios_me_be-me_inv_2x4x4",
        "value": "Developed_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "developed_ex_us_32_portfolios_me_be-me_inv_2x4x4",
        "value": "Developed_ex_US_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "europe_32_portfolios_me_be-me_inv_2x4x4",
        "value": "Europe_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "japan_32_portfolios_me_be-me_inv_2x4x4",
        "value": "Japan_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_32_portfolios_me_be-me_inv_2x4x4",
        "value": "Asia_Pacific_ex_Japan_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "north_america_32_portfolios_me_be-me_inv_2x4x4",
        "value": "North_America_32_Portfolios_ME_BE-ME_INV(TA)_2x4x4_CSV.zip",
    },
    {
        "label": "developed_32_portfolios_me_inv_op_2x4x4",
        "value": "Developed_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "developed_ex_us_32_portfolios_me_inv_op_2x4x4",
        "value": "Developed_ex_US_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "europe_32_portfolios_me_inv_op_2x4x4",
        "value": "Europe_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "japan_32_portfolios_me_inv_op_2x4x4",
        "value": "Japan_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "asia_pacific_ex_japan_32_portfolios_me_inv_op_2x4x4",
        "value": "Asia_Pacific_ex_Japan_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "north_america_32_portfolios_me_inv_op_2x4x4",
        "value": "North_America_32_Portfolios_ME_INV(TA)_OP_2x4x4_CSV.zip",
    },
    {
        "label": "emerging_markets_6_portfolios_me_be-me",
        "value": "Emerging_Markets_6_Portfolios_ME_BE-ME_CSV.zip",
    },
    {
        "label": "emerging_markets_6_portfolios_me_op",
        "value": "Emerging_Markets_6_Portfolios_ME_OP_CSV.zip",
    },
    {
        "label": "emerging_markets_6_portfolios_me_inv",
        "value": "Emerging_Markets_6_Portfolios_ME_INV_CSV.zip",
    },
    {
        "label": "emerging_markets_6_portfolios_me_prior_12_2",
        "value": "Emerging_Markets_6_Portfolios_ME_Prior_12_2_CSV.zip",
    },
    {
        "label": "emerging_markets_4_portfolios_be-me_op",
        "value": "Emerging_Markets_4_Portfolios_BE-ME_OP_CSV.zip",
    },
    {
        "label": "emerging_markets_4_portfolios_op_inv",
        "value": "Emerging_Markets_4_Portfolios_OP_INV_CSV.zip",
    },
    {
        "label": "emerging_markets_4_portfolios_be-me_inv",
        "value": "Emerging_Markets_4_Portfolios_BE-ME_INV_CSV.zip",
    },
]

RegionalPortfolios = Literal[
    "asia_pacific_ex_japan_25_portfolios_me_be-me",
    "asia_pacific_ex_japan_25_portfolios_me_be-me_daily",
    "asia_pacific_ex_japan_25_portfolios_me_inv",
    "asia_pacific_ex_japan_25_portfolios_me_inv_daily",
    "asia_pacific_ex_japan_25_portfolios_me_op",
    "asia_pacific_ex_japan_25_portfolios_me_op_daily",
    "asia_pacific_ex_japan_25_portfolios_me_prior_12_2",
    "asia_pacific_ex_japan_25_portfolios_me_prior_250_20_daily",
    "asia_pacific_ex_japan_32_portfolios_me_be-me_inv_2x4x4",
    "asia_pacific_ex_japan_32_portfolios_me_be-me_op_2x4x4",
    "asia_pacific_ex_japan_32_portfolios_me_inv_op_2x4x4",
    "asia_pacific_ex_japan_6_portfolios_me_be-me",
    "asia_pacific_ex_japan_6_portfolios_me_be-me_daily",
    "asia_pacific_ex_japan_6_portfolios_me_inv",
    "asia_pacific_ex_japan_6_portfolios_me_inv_daily",
    "asia_pacific_ex_japan_6_portfolios_me_op",
    "asia_pacific_ex_japan_6_portfolios_me_op_daily",
    "asia_pacific_ex_japan_6_portfolios_me_prior_12_2",
    "asia_pacific_ex_japan_6_portfolios_me_prior_250_20_daily",
    "developed_25_portfolios_me_be-me",
    "developed_25_portfolios_me_be-me_daily",
    "developed_25_portfolios_me_inv",
    "developed_25_portfolios_me_inv_daily",
    "developed_25_portfolios_me_op",
    "developed_25_portfolios_me_op_daily",
    "developed_25_portfolios_me_prior_12_2",
    "developed_25_portfolios_me_prior_250_20_daily",
    "developed_32_portfolios_me_be-me_inv_2x4x4",
    "developed_32_portfolios_me_be-me_op_2x4x4",
    "developed_32_portfolios_me_inv_op_2x4x4",
    "developed_6_portfolios_me_be-me",
    "developed_6_portfolios_me_be-me_daily",
    "developed_6_portfolios_me_inv",
    "developed_6_portfolios_me_inv_daily",
    "developed_6_portfolios_me_op",
    "developed_6_portfolios_me_op_daily",
    "developed_6_portfolios_me_prior_12_2",
    "developed_6_portfolios_me_prior_250_20_daily",
    "developed_ex_us_25_portfolios_me_be-me",
    "developed_ex_us_25_portfolios_me_be-me_daily",
    "developed_ex_us_25_portfolios_me_inv",
    "developed_ex_us_25_portfolios_me_inv_daily",
    "developed_ex_us_25_portfolios_me_op",
    "developed_ex_us_25_portfolios_me_op_daily",
    "developed_ex_us_25_portfolios_me_prior_12_2",
    "developed_ex_us_25_portfolios_me_prior_250_20_daily",
    "developed_ex_us_32_portfolios_me_be-me_inv_2x4x4",
    "developed_ex_us_32_portfolios_me_be-me_op_2x4x4",
    "developed_ex_us_32_portfolios_me_inv_op_2x4x4",
    "developed_ex_us_6_portfolios_me_be-me",
    "developed_ex_us_6_portfolios_me_be-me_daily",
    "developed_ex_us_6_portfolios_me_inv",
    "developed_ex_us_6_portfolios_me_inv_daily",
    "developed_ex_us_6_portfolios_me_op",
    "developed_ex_us_6_portfolios_me_op_daily",
    "developed_ex_us_6_portfolios_me_prior_12_2",
    "developed_ex_us_6_portfolios_me_prior_250_20_daily",
    "emerging_markets_4_portfolios_be-me_inv",
    "emerging_markets_4_portfolios_be-me_op",
    "emerging_markets_4_portfolios_op_inv",
    "emerging_markets_6_portfolios_me_be-me",
    "emerging_markets_6_portfolios_me_inv",
    "emerging_markets_6_portfolios_me_op",
    "emerging_markets_6_portfolios_me_prior_12_2",
    "europe_25_portfolios_me_be-me",
    "europe_25_portfolios_me_be-me_daily",
    "europe_25_portfolios_me_inv",
    "europe_25_portfolios_me_inv_daily",
    "europe_25_portfolios_me_op",
    "europe_25_portfolios_me_op_daily",
    "europe_25_portfolios_me_prior_12_2",
    "europe_25_portfolios_me_prior_250_20_daily",
    "europe_32_portfolios_me_be-me_inv_2x4x4",
    "europe_32_portfolios_me_be-me_op_2x4x4",
    "europe_32_portfolios_me_inv_op_2x4x4",
    "europe_6_portfolios_me_be-me",
    "europe_6_portfolios_me_be-me_daily",
    "europe_6_portfolios_me_inv",
    "europe_6_portfolios_me_inv_daily",
    "europe_6_portfolios_me_op",
    "europe_6_portfolios_me_op_daily",
    "europe_6_portfolios_me_prior_12_2",
    "europe_6_portfolios_me_prior_250_20_daily",
    "japan_25_portfolios_me_be-me",
    "japan_25_portfolios_me_be-me_daily",
    "japan_25_portfolios_me_inv",
    "japan_25_portfolios_me_inv_daily",
    "japan_25_portfolios_me_op",
    "japan_25_portfolios_me_op_daily",
    "japan_25_portfolios_me_prior_12_2",
    "japan_25_portfolios_me_prior_250_20_daily",
    "japan_32_portfolios_me_be-me_inv_2x4x4",
    "japan_32_portfolios_me_be-me_op_2x4x4",
    "japan_32_portfolios_me_inv_op_2x4x4",
    "japan_6_portfolios_me_be-me",
    "japan_6_portfolios_me_be-me_daily",
    "japan_6_portfolios_me_inv",
    "japan_6_portfolios_me_inv_daily",
    "japan_6_portfolios_me_op",
    "japan_6_portfolios_me_op_daily",
    "japan_6_portfolios_me_prior_12_2",
    "japan_6_portfolios_me_prior_250_20_daily",
    "north_america_25_portfolios_me_be-me",
    "north_america_25_portfolios_me_be-me_daily",
    "north_america_25_portfolios_me_inv",
    "north_america_25_portfolios_me_inv_daily",
    "north_america_25_portfolios_me_op",
    "north_america_25_portfolios_me_op_daily",
    "north_america_25_portfolios_me_prior_12_2",
    "north_america_25_portfolios_me_prior_250_20_daily",
    "north_america_32_portfolios_me_be-me_inv_2x4x4",
    "north_america_32_portfolios_me_be-me_op_2x4x4",
    "north_america_32_portfolios_me_inv_op_2x4x4",
    "north_america_6_portfolios_me_be-me",
    "north_america_6_portfolios_me_be-me_daily",
    "north_america_6_portfolios_me_inv",
    "north_america_6_portfolios_me_inv_daily",
    "north_america_6_portfolios_me_op",
    "north_america_6_portfolios_me_op_daily",
    "north_america_6_portfolios_me_prior_12_2",
    "north_america_6_portfolios_me_prior_250_20_daily",
]

BREAKPOINT_CHOICES = [
    {"value": "me", "label": "Market Equity (ME)"},
    {"value": "be-me", "label": "Book Equity to Market Equity (BE/ME)"},
    {"value": "op", "label": "Operating Profitability (OP)"},
    {"value": "inv", "label": "Investment (INV)"},
    {"value": "e-p", "label": "Earnings to Price (E/P)"},
    {"value": "cf-p", "label": "Cash Flow to Price (CF/P)"},
    {"value": "d-p", "label": "Dividends to Price (D/P)"},
    {"value": "2-12", "label": "Prior 2-12 Month Returns"},
]

BREAKPOINT_FILES = {
    "me": "ME_Breakpoints_CSV.zip",
    "be-me": "BE-ME_Breakpoints_CSV.zip",
    "op": "OP_Breakpoints_CSV.zip",
    "inv": "INV_Breakpoints_CSV.zip",
    "e-p": "E-P_Breakpoints_CSV.zip",
    "cf-p": "CF-P_Breakpoints_CSV.zip",
    "d-p": "D-P_Breakpoints_CSV.zip",
    "2-12": "Prior_2-12_Breakpoints_CSV.zip",
}

BreakpointChoices = Literal[
    "me",
    "be-me",
    "op",
    "inv",
    "e-p",
    "cf-p",
    "d-p",
    "2-12",
]
