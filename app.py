"""
Streamlit Web App for Workout Program Generation
================================================

This application provides a simple web interface for coaches to build
custom workout programs.  Users can select the program length, days
per week, primary focus areas, workout styles, volume and intensity
levels, and desired progression model.  Based on these inputs and
user‑defined weekly set targets, the app automatically generates a
day‑by‑day plan that includes warm‑up, WOD, and accessory sections for
each session.

The app runs entirely in the browser via Streamlit.  When you click
"Generate Program," the selected parameters are used to assemble a
schedule, drawing exercises from a built‑in database.  You can
preview the resulting program and download it as an Excel file.

Note: To run this app locally, install the required packages and
launch via the Streamlit command:

    pip install streamlit pandas openpyxl
    streamlit run app.py

"""

import math
import datetime
from typing import Dict, List, Tuple

import random
import streamlit as st
import pandas as pd

# -----------------------------------------------------------------------------
# Data definitions
# -----------------------------------------------------------------------------

# Define lists for dropdown menus.  These mirror the Lists sheet from the
# template.  Feel free to modify or extend these lists to suit your needs.
WOD_STYLES = ["AMRAP", "For Time", "OTM/EMOM", "Tabata", "Alternating"]
MUSCLE_GROUPS = [
    "Full Body",
    "Legs – Quads",
    "Legs – Hamstrings",
    "Glutes",
    "Chest",
    "Back",
    "Shoulders",
    "Arms",
    "Core",
]
MOVEMENT_PATTERNS = [
    "Squat",
    "Hinge",
    "Push – Horizontal",
    "Push – Vertical",
    "Pull – Horizontal",
    "Pull – Vertical",
    "Carry",
    "Core – Stability",
    "Core – Rotation",
]
WARM_UP_TYPES = [
    "Dynamic Warm-Up + Activation",
    "Pre-exhaust Warm-Up",
    "Activation & Mobility",
    "Traditional Warm-Up",
]
FOCUS_AREAS = [
    "Strength (Low Speed)",
    "Explosiveness (High Speed)",
    "Speed (acceleration/deceleration)",
    "Agility (Reactiveness/Awareness)",
    "Coordination (Technical Skill)",
    "Stamina (Conditioning)",
    "Flexibility/Pliability",
    "Stability (Balance)",
]
VOLUME_LEVELS = {
    "Low Volume": (2, 8),
    "Medium Volume": (6, 15),
    "High Volume": (12, 15),  # treat 12+ as 12–15 for numeric purposes
}
INTENSITY_LEVELS = {
    "Low Intensity": (6, 7),
    "Medium Intensity": (7, 8),
    "High Intensity": (9, 10),
}
PROGRESSION_TYPES = ["Linear", "Undulating", "Block", "Conjugate"]

# A minimal exercise database keyed by (muscle group, movement pattern).
EXERCISE_DB: Dict[Tuple[str, str], List[str]] = {
    ("Legs – Quads", "Squat"): ["Air Squat", "Goblet Squat", "Barbell Back Squat"],
    ("Legs – Hamstrings", "Hinge"): ["Romanian Deadlift", "Barbell Deadlift"],
    ("Glutes", "Hinge"): ["Glute Bridge", "Hip Thrust"],
    ("Chest", "Push – Horizontal"): ["Push-Up", "Bench Press"],
    ("Back", "Pull – Vertical"): ["Pull-Up"],
    ("Back", "Pull – Horizontal"): ["Bent-Over Row"],
    ("Core", "Core – Stability"): ["Plank"],
    ("Core", "Core – Rotation"): ["Weighted Russian Twist"],
    ("Full Body", "Carry"): ["Farmer's Carry"],
}


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def distribute_targets(targets: Dict[str, int], num_days: int) -> List[str]:
    """Distribute targets proportionally across a number of days.

    Parameters
    ----------
    targets : Dict[str, int]
        Mapping from target names to sets per week.
    num_days : int
        Number of training days per week.

    Returns
    -------
    List[str]
        List of length ``num_days`` assigning each day a target.  If
        ``targets`` is empty, returns a list of empty strings.
    """
    if not targets or num_days <= 0:
        return ["" for _ in range(num_days)]
    total_sets = sum(max(v, 1) for v in targets.values())
    # Compute allocation weight per target
    weights = {t: v / total_sets * num_days for t, v in targets.items()}
    # Floor allocations and allocate remaining based on fractional parts
    floor_days = {t: int(math.floor(w)) for t, w in weights.items()}
    remaining = num_days - sum(floor_days.values())
    fractional = sorted([(w - floor_days[t], t) for t, w in weights.items()], reverse=True)
    schedule = []
    # Build initial schedule from floor allocations
    for t, count in floor_days.items():
        schedule.extend([t] * count)
    # Allocate remaining days
    i = 0
    while len(schedule) < num_days:
        _, t = fractional[i % len(fractional)]
        schedule.append(t)
        i += 1
    # Interleave targets to avoid clumping similar targets together
    unique = list(targets.keys())
    interleaved = []
    counts = {t: schedule.count(t) for t in unique}
    while len(interleaved) < num_days:
        for t in unique:
            if counts[t] > 0:
                interleaved.append(t)
                counts[t] -= 1
                if len(interleaved) == num_days:
                    break
    return interleaved


def choose_exercise(mg: str, mp: str) -> str:
    """Choose an exercise matching the given muscle group and movement pattern.

    Fallback rules: match by muscle group only or movement pattern only.
    Returns empty string if no match is found.
    """
    if (mg, mp) in EXERCISE_DB and EXERCISE_DB[(mg, mp)]:
        return EXERCISE_DB[(mg, mp)][0]
    # Fallback to matching by muscle group
    for (m, p), ex_list in EXERCISE_DB.items():
        if m == mg and ex_list:
            return ex_list[0]
    # Fallback to matching by movement pattern
    for (m, p), ex_list in EXERCISE_DB.items():
        if p == mp and ex_list:
            return ex_list[0]
    return ""


def adjust_reps(base_range: Tuple[int, int], week: int, total_weeks: int, progression: str,
                day_of_week: int = 1, days_per_week: int = 3) -> Tuple[int, int]:
    """Adjust the rep range based on the progression type.

    For linear progression, reps increase slightly each week.  For
    undulating progression, reps vary in a repeating pattern across
    weeks.  Block progression splits the program into three phases
    emphasising volume, balanced work and intensity.  Conjugate
    progression assigns different schemes to each day of the week.

    Parameters
    ----------
    base_range : tuple[int, int]
        Base (min, max) reps selected from the volume level.
    week : int
        Current week index (1-indexed).
    total_weeks : int
        Total number of weeks in the program.
    progression : str
        Progression type (Linear, Undulating, Block, Conjugate).
    day_of_week : int
        Day index within the current week (1-indexed) for conjugate
        progression.
    days_per_week : int
        Total training days per week.

    Returns
    -------
    Tuple[int, int]
        Adjusted (min, max) reps.
    """
    low, high = base_range
    if progression.lower() == "linear":
        # Increase reps slightly each week (e.g. add 1 rep every week)
        increment = week - 1
        return low + increment, high + increment
    elif progression.lower() == "undulating":
        # Define a repeating cycle: high volume, low volume, medium volume
        cycle = ["High Volume", "Low Volume", "Medium Volume"]
        index = (week - 1) % len(cycle)
        label = cycle[index]
        return VOLUME_LEVELS[label]
    elif progression.lower() == "block":
        # Divide program into three blocks
        third = max(1, total_weeks // 3)
        if week <= third:
            return VOLUME_LEVELS["High Volume"]
        elif week <= 2 * third:
            return VOLUME_LEVELS["Medium Volume"]
        else:
            return VOLUME_LEVELS["Low Volume"]
    elif progression.lower() == "conjugate":
        # Assign different schemes per day: Day1 max effort (low volume), Day2 dynamic (medium), Day3 repetition (high)
        schemes = ["Low Volume", "Medium Volume", "High Volume"]
        idx = (day_of_week - 1) % len(schemes)
        label = schemes[idx]
        return VOLUME_LEVELS[label]
    # Default: no change
    return base_range


def adjust_rpe(base_rpe: Tuple[int, int], week: int, total_weeks: int, progression: str,
               day_of_week: int = 1, days_per_week: int = 3) -> Tuple[int, int]:
    """Adjust the RPE range based on progression type.

    Uses similar logic to `adjust_reps` to vary intensity across the program.
    """
    low, high = base_rpe
    if progression.lower() == "linear":
        # Gradually increase intensity: add 0.5 RPE every two weeks
        increment = (week - 1) // 2 * 0.5
        return int(low + increment), int(high + increment)
    elif progression.lower() == "undulating":
        cycle = ["Low Intensity", "High Intensity", "Medium Intensity"]
        index = (week - 1) % len(cycle)
        label = cycle[index]
        return INTENSITY_LEVELS[label]
    elif progression.lower() == "block":
        third = max(1, total_weeks // 3)
        if week <= third:
            return INTENSITY_LEVELS["Low Intensity"]
        elif week <= 2 * third:
            return INTENSITY_LEVELS["Medium Intensity"]
        else:
            return INTENSITY_LEVELS["High Intensity"]
    elif progression.lower() == "conjugate":
        schemes = ["High Intensity", "Medium Intensity", "Low Intensity"]
        idx = (day_of_week - 1) % len(schemes)
        label = schemes[idx]
        return INTENSITY_LEVELS[label]
    return base_rpe


def select_exercises(mg: str, mp: str, num: int) -> List[str]:
    """Return a list of ``num`` exercises matching the given muscle group and pattern.

    If there are not enough unique exercises in the database, the list
    repeats entries as needed.  The order of exercises is determined
    randomly to introduce variety.

    Parameters
    ----------
    mg : str
        Muscle group.
    mp : str
        Movement pattern.
    num : int
        Number of exercises to select.

    Returns
    -------
    List[str]
        List of exercise names of length ``num``.
    """
    if num <= 0:
        return []
    choices: List[str] = []
    # Primary matches
    key = (mg, mp)
    if key in EXERCISE_DB:
        choices.extend(EXERCISE_DB[key])
    # Secondary matches: same muscle group
    for (m, p), ex_list in EXERCISE_DB.items():
        if m == mg and (m, p) != key:
            choices.extend(ex_list)
    # Secondary matches: same pattern
    for (m, p), ex_list in EXERCISE_DB.items():
        if p == mp and (m, p) != key and m != mg:
            choices.extend(ex_list)
    # If still empty, take all exercises in database
    if not choices:
        for ex_list in EXERCISE_DB.values():
            choices.extend(ex_list)
    # Ensure deterministic order but vary selection using random sample
    # Remove duplicates
    unique_choices = list(dict.fromkeys(choices))
    # If not enough unique exercises, repeat the list
    result: List[str] = []
    while len(result) < num:
        # Shuffle a copy to vary order
        pool = unique_choices.copy()
        random.shuffle(pool)
        for ex in pool:
            result.append(ex)
            if len(result) == num:
                break
    return result[:num]


def generate_program(num_weeks: int, days_per_week: int,
                     muscle_targets: Dict[str, int], pattern_targets: Dict[str, int],
                     warm_style: str, wod_style: str, acc_style: str,
                     volume_level: str, intensity_level: str,
                     progression: str,
                     num_wod_ex: int = 2, num_acc_ex: int = 2,
                     amrap_format: str = None) -> pd.DataFrame:
    """Assemble the program schedule based on user selections.

    Parameters
    ----------
    num_weeks : int
        Number of weeks in the program.
    days_per_week : int
        Number of training days per week.
    muscle_targets : Dict[str, int]
        Sets per week for each muscle group.
    pattern_targets : Dict[str, int]
        Sets per week for each movement pattern.
    warm_style : str
        Warm-up style.
    wod_style : str
        WOD style.
    acc_style : str
        Accessory style.
    volume_level : str
        Base volume level (Low/Medium/High Volume).
    intensity_level : str
        Base intensity level (Low/Medium/High Intensity).
    progression : str
        Progression type (Linear, Undulating, Block, Conjugate).

    Returns
    -------
    pd.DataFrame
        A DataFrame representing the program outline.
    """
    base_reps = VOLUME_LEVELS.get(volume_level, (6, 15))
    base_rpe = INTENSITY_LEVELS.get(intensity_level, (7, 8))
    muscle_schedule = distribute_targets(muscle_targets, days_per_week)
    pattern_schedule = distribute_targets(pattern_targets, days_per_week)
    # Ensure lists have correct length
    if not muscle_schedule:
        muscle_schedule = ["" for _ in range(days_per_week)]
    if not pattern_schedule:
        pattern_schedule = ["" for _ in range(days_per_week)]
    rows = []
    for week in range(1, num_weeks + 1):
        for day_idx in range(days_per_week):
            day = day_idx + 1
            mg = muscle_schedule[day_idx]
            mp = pattern_schedule[day_idx]
            # Select multiple exercises
            wod_ex_list = select_exercises(mg, mp, num_wod_ex)
            # Secondary selection for accessory: rotate to next target and pick exercises
            acc_mg = muscle_schedule[(day_idx + 1) % len(muscle_schedule)] if muscle_schedule else ""
            acc_mp = pattern_schedule[(day_idx + 1) % len(pattern_schedule)] if pattern_schedule else ""
            acc_ex_list = select_exercises(acc_mg, acc_mp, num_acc_ex)
            # Compute reps and RPE ranges (one per section; will randomise per exercise later)
            reps_range = adjust_reps(base_reps, week, num_weeks, progression, day, days_per_week)
            rpe_range = adjust_rpe(base_rpe, week, num_weeks, progression, day, days_per_week)
            # Determine sets per day for each section (based on muscle targets)
            sets_wod_total = math.ceil(muscle_targets.get(mg, 0) / days_per_week) if mg else 0
            sets_acc_total = math.ceil(muscle_targets.get(acc_mg, 0) / days_per_week) if acc_mg else 0
            # Helper to split sets across exercises; ensures at least one set if total_sets > 0
            def split_sets(total_sets: int, num_ex: int) -> List[int]:
                if total_sets <= 0 or num_ex <= 0:
                    return [0] * num_ex
                base = total_sets // num_ex
                remainder = total_sets % num_ex
                sets_list = [base] * num_ex
                for i in range(remainder):
                    sets_list[i] += 1
                sets_list = [max(1, s) for s in sets_list]
                return sets_list
            wod_sets_list = split_sets(sets_wod_total, len(wod_ex_list))
            acc_sets_list = split_sets(sets_acc_total, len(acc_ex_list))
            # Warm-Up row
            rows.append({
                "Week": week,
                "Day": day,
                "Section": "Warm-Up",
                "Style": warm_style,
                "Muscle Group": "",
                "Movement Pattern": "",
                "Exercise": "",
                "Sets": "",
                "Reps/Time": "",
                "RPE Range": f"{rpe_range[0]}-{rpe_range[1]} RPE" if rpe_range[0] != rpe_range[1] else f"{rpe_range[0]} RPE",
            })
            # WOD rows
            for ex, sets_per_ex in zip(wod_ex_list, wod_sets_list):
                # Choose random rep within range unless AMRAP format is set
                if wod_style == "AMRAP" and amrap_format:
                    rep_time_str = amrap_format.replace("(", "").replace(")", "")  # clean parentheses
                else:
                    rep_val = random.randint(reps_range[0], reps_range[1])
                    rep_time_str = f"{rep_val} reps"
                rows.append({
                    "Week": week,
                    "Day": day,
                    "Section": "WOD",
                    "Style": wod_style,
                    "Muscle Group": mg,
                    "Movement Pattern": mp,
                    "Exercise": ex,
                    "Sets": sets_per_ex if sets_per_ex > 0 else "",
                    "Reps/Time": rep_time_str,
                    "RPE Range": f"{rpe_range[0]}-{rpe_range[1]} RPE" if rpe_range[0] != rpe_range[1] else f"{rpe_range[0]} RPE",
                })
            # Accessory rows
            for ex, sets_per_ex in zip(acc_ex_list, acc_sets_list):
                if wod_style == "AMRAP" and amrap_format:
                    rep_time_str = amrap_format.replace("(", "").replace(")", "")
                else:
                    rep_val = random.randint(reps_range[0], reps_range[1])
                    rep_time_str = f"{rep_val} reps"
                rows.append({
                    "Week": week,
                    "Day": day,
                    "Section": "Accessory",
                    "Style": acc_style,
                    "Muscle Group": acc_mg,
                    "Movement Pattern": acc_mp,
                    "Exercise": ex,
                    "Sets": sets_per_ex if sets_per_ex > 0 else "",
                    "Reps/Time": rep_time_str,
                    "RPE Range": f"{rpe_range[0]}-{rpe_range[1]} RPE" if rpe_range[0] != rpe_range[1] else f"{rpe_range[0]} RPE",
                })
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Streamlit page layout
# -----------------------------------------------------------------------------

def main() -> None:
    st.title("Workout Program Generator")
    st.write("Select your program parameters and generate a customised plan.")
    # Sidebar inputs
    st.sidebar.header("Program Setup")
    num_weeks = st.sidebar.selectbox("Number of Weeks", list(range(4, 13)), index=4)
    days_per_week = st.sidebar.selectbox("Days per Week", list(range(1, 8)), index=2)
    focus_areas = st.sidebar.multiselect("Focus Areas (choose up to 5)", FOCUS_AREAS, max_selections=5)
    warm_style = st.sidebar.selectbox("Warm-Up Style", WARM_UP_TYPES)
    wod_style = st.sidebar.selectbox("WOD Style", WOD_STYLES)
    acc_style = st.sidebar.selectbox("Accessory Style", WOD_STYLES)
    volume_level = st.sidebar.selectbox("Volume Level", list(VOLUME_LEVELS.keys()))
    intensity_level = st.sidebar.selectbox("Intensity Level", list(INTENSITY_LEVELS.keys()))
    progression = st.sidebar.selectbox("Progression Type", PROGRESSION_TYPES)
    # AMRAP configuration: only show when WOD style is AMRAP
    amrap_format = None
    if wod_style == "AMRAP":
        st.sidebar.markdown("---")
        st.sidebar.header("AMRAP Format")
        amrap_format = st.sidebar.radio(
            "How should the 20-minute AMRAP be structured?",
            options=[
                "Single 20-min AMRAP",
                "Two 8-min sections (2-min rest)",
                "Four 4-min sections (1-min rest)",
            ],
            index=0,
        )
    # Number of exercises per section
    st.sidebar.markdown("---")
    st.sidebar.header("Exercises per Section")
    num_wod_ex = st.sidebar.number_input(
        "Number of WOD Exercises", min_value=2, max_value=5, value=2, step=1,
        help="How many exercises to include in each WOD session."
    )
    num_acc_ex = st.sidebar.number_input(
        "Number of Accessory Exercises", min_value=2, max_value=5, value=2, step=1,
        help="How many exercises to include in each accessory block."
    )
    st.sidebar.markdown("---")
    st.sidebar.header("Sets per Week Targets")
    st.sidebar.write("Enter the number of sets per week for each muscle group and movement pattern. Leave blank or zero to skip.")
    # Collect muscle group targets
    muscle_targets: Dict[str, int] = {}
    st.sidebar.subheader("Muscle Groups")
    for mg in MUSCLE_GROUPS:
        val = st.sidebar.number_input(f"{mg}", min_value=0, step=1, value=0)
        if val > 0:
            muscle_targets[mg] = val
    # Collect movement pattern targets
    pattern_targets: Dict[str, int] = {}
    st.sidebar.subheader("Movement Patterns")
    for mp in MOVEMENT_PATTERNS:
        val = st.sidebar.number_input(f"{mp}", min_value=0, step=1, value=0)
        if val > 0:
            pattern_targets[mp] = val
    # Main area
    if st.button("Generate Program"):
        if num_weeks <= 0 or days_per_week <= 0:
            st.error("Please specify a positive number of weeks and days per week.")
        else:
            program_df = generate_program(
                num_weeks=num_weeks,
                days_per_week=days_per_week,
                muscle_targets=muscle_targets,
                pattern_targets=pattern_targets,
                warm_style=warm_style,
                wod_style=wod_style,
                acc_style=acc_style,
                volume_level=volume_level,
                intensity_level=intensity_level,
                progression=progression,
                num_wod_ex=int(num_wod_ex),
                num_acc_ex=int(num_acc_ex),
                amrap_format=amrap_format,
            )
            st.success("Program generated!")
            st.dataframe(program_df)
            # Provide download option as Excel
            with pd.ExcelWriter("program_output.xlsx", engine="openpyxl") as writer:
                program_df.to_excel(writer, index=False, sheet_name="Program Outline")
            with open("program_output.xlsx", "rb") as f:
                st.download_button("Download as Excel", f, file_name="program_output.xlsx")
    # Show instructions
    st.markdown(
        """
        ### Instructions
        1. Use the sidebar to configure your program length, training frequency, focus areas, styles, and progression type.
        2. Specify how many sets per week you want for each muscle group and movement pattern.  Leave a field at 0 to ignore it.
        3. Click **Generate Program** to build your training outline.  The program will automatically distribute your targets across the selected days and adjust rep ranges and intensities according to the progression model.
        4. Preview the results in the table, then click **Download as Excel** to save the plan for further editing.

        The progression models adjust sets and reps over time:
        - **Linear:** Reps increase slightly each week.
        - **Undulating:** Volumes and intensities fluctuate in a high‑low‑medium pattern across weeks.
        - **Block:** The program is split into three phases emphasising volume, balanced work and intensity.
        - **Conjugate:** Each day uses a different method (max effort, dynamic effort, repetition) within the week.
        """
    )


if __name__ == "__main__":
    main()
