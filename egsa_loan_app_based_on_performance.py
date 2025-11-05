# save as egsa_loan_app.py and run: streamlit run egsa_loan_app.py
import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, timedelta
import math
from io import BytesIO  # ✅ added for Excel download

DB = "egsa_loans.db"

# ---------- DB helpers ----------
def init_db():
    con = sqlite3.connect(DB, check_same_thread=False)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    joined_date TEXT DEFAULT (date('now'))
                  )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS loans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL,
                    new_members_count INTEGER NOT NULL,
                    principal INTEGER NOT NULL,
                    term_months INTEGER NOT NULL,
                    annual_rate REAL NOT NULL,
                    interest_upfront REAL NOT NULL,
                    disbursed_amount REAL NOT NULL,
                    disbursed_date TEXT DEFAULT (date('now')),
                    due_date TEXT,
                    status TEXT DEFAULT 'active',
                    FOREIGN KEY (member_id) REFERENCES members(id)
                  )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS repayments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loan_id INTEGER NOT NULL,
                    payment_date TEXT DEFAULT (date('now')),
                    amount REAL NOT NULL,
                    payment_type TEXT,
                    FOREIGN KEY (loan_id) REFERENCES loans(id)
                  )""")
    con.commit()
    return con

con = init_db()

# ---------- Business logic ----------
def loan_offer_by_new_members(new_count):
    if new_count == 1:
        return (50000, 3, 0.09)
    elif new_count == 2:
        return (100000, 6, 0.09)
    elif new_count == 3:
        return (100000, 9, 0.06)
    elif new_count > 3:
        return (100000, 12, 0.0)
    else:
        raise ValueError("new_count must be >=1")

def compute_interest_upfront(principal, annual_rate, term_months):
    return principal * annual_rate * (1)

def build_schedule(principal, term_months, annual_rate, disbursed_date):
    schedule = []
    interest_upfront = compute_interest_upfront(principal, annual_rate, term_months)
    disbursed_amount = principal - interest_upfront
    if annual_rate == 0.0 and term_months == 12:
        # lump-sum at month 12
        due = pd.to_datetime(disbursed_date) + pd.DateOffset(months=12)
        schedule.append({
            "installment_no": 1,
            "due_date": due.date().isoformat(),
            "amount_due": principal,
            "principal_component": principal,
            "notes": "Lump-sum at month 12"
        })
    else:
        monthly_principal = principal / term_months
        for m in range(1, term_months+1):
            due = pd.to_datetime(disbursed_date) + pd.DateOffset(months=m)
            schedule.append({
                "installment_no": m,
                "due_date": due.date().isoformat(),
                "amount_due": round(monthly_principal,2),
                "principal_component": round(monthly_principal,2),
                "notes": ""
            })
    return interest_upfront, disbursed_amount, pd.DataFrame(schedule)

# ---------- UI ----------
st.title("EGSA — Member Referral Loan App")

st.sidebar.header("Actions")
action = st.sidebar.selectbox("Choose action", ["Register member", "Create loan", "Record repayment", "View loans"])

# Register
if action == "Register member":
    st.header("Register member")
    name = st.text_input("Member name")
    phone = st.text_input("Phone (optional)")
    if st.button("Register"):
        if not name:
            st.warning("Please enter a name.")
        else:
            cur = con.cursor()
            cur.execute("INSERT INTO members (name, phone) VALUES (?, ?)", (name, phone))
            con.commit()
            st.success(f"Member '{name}' registered.")

# Create loan
if action == "Create loan":
    st.header("Create loan for member")
    cur = con.cursor()
    members = pd.read_sql_query("SELECT id, name FROM members", con)
    if members.empty:
        st.info("No members found. Please register first.")
    else:
        member_select = st.selectbox("Choose member", options=members['id'].tolist(), format_func=lambda x: members.set_index('id').loc[x,'name'])
        new_count = st.number_input("Number of new members this member brought", min_value=1, step=1, value=1)
        create = st.button("Create loan")
        if create:
            principal, term_months, annual_rate = loan_offer_by_new_members(new_count)
            disbursed_date = pd.Timestamp(date.today()).date().isoformat()
            interest_upfront = compute_interest_upfront(principal, annual_rate, term_months)
            disbursed_amount = principal - interest_upfront
            due_date = (pd.to_datetime(disbursed_date) + pd.DateOffset(months=term_months)).date().isoformat()
            cur.execute("""INSERT INTO loans (member_id, new_members_count, principal, term_months, annual_rate, interest_upfront, disbursed_amount, disbursed_date, due_date)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (member_select, new_count, principal, term_months, annual_rate, interest_upfront, disbursed_amount, disbursed_date, due_date))
            con.commit()
            st.success("Loan created.")
            st.write("**Loan summary**")
            st.write({
                "member": members.set_index('id').loc[member_select,'name'],
                "principal": principal,
                "term_months": term_months,
                "annual_rate": f"{annual_rate*100:.2f}%",
                "interest_upfront": round(interest_upfront,2),
                "disbursed_amount": round(disbursed_amount,2),
                "disbursed_date": disbursed_date,
                "due_date": due_date
            })
            _, _, sched = build_schedule(principal, term_months, annual_rate, disbursed_date)
            st.write("Repayment schedule (installments refer to principal; interest already deducted upfront where applicable)")
            st.dataframe(sched)

# Record repayment
if action == "Record repayment":
    st.header("Record repayment")
    loans_df = pd.read_sql_query("SELECT l.id, l.member_id, m.name as member_name, l.principal, l.term_months, l.annual_rate, l.interest_upfront, l.disbursed_amount, l.disbursed_date, l.due_date, l.status FROM loans l JOIN members m ON l.member_id = m.id", con)
    if loans_df.empty:
        st.info("No loans found.")
    else:
        loan_choice = st.selectbox("Select loan", loans_df['id'].tolist(), format_func=lambda x: f"Loan #{x} — {loans_df.set_index('id').loc[x,'member_name']}")
        loan = loans_df.set_index('id').loc[loan_choice].to_dict()
        st.write("Loan details", loan)
        amount = st.number_input("Payment amount", min_value=0.0, value=0.0, step=1.0)
        if st.button("Save payment"):
            cur = con.cursor()
            cur.execute("INSERT INTO repayments (loan_id, amount) VALUES (?, ?)", (loan_choice, amount))
            # optionally update status if fully repaid:
            total_paid = pd.read_sql_query("SELECT IFNULL(SUM(amount),0) as s FROM repayments WHERE loan_id = ?", con, params=(loan_choice,)).iloc[0,0]
            principal = loan['principal']
            if total_paid >= principal:
                cur.execute("UPDATE loans SET status = 'closed' WHERE id = ?", (loan_choice,))
            con.commit()
            st.success("Payment recorded.")

# View loans
if action == "View loans":
    st.header("All loans")
    loans_df = pd.read_sql_query("SELECT l.id, l.member_id, m.name as member_name, l.new_members_count, l.principal, l.term_months, l.annual_rate, l.interest_upfront, l.disbursed_amount, l.disbursed_date, l.due_date, l.status FROM loans l JOIN members m ON l.member_id = m.id", con)
    if loans_df.empty:
        st.info("No loans yet.")
    else:
        st.dataframe(loans_df)

        # ✅ --- DOWNLOAD BUTTON ADDED HERE ---
        st.subheader("Download Loan View")
        buffer = BytesIO()
        loans_df.to_excel(buffer, index=False)
        buffer.seek(0)
        st.download_button(
            label="📥 Download Loans (Excel)",
            data=buffer,
            file_name="EGSA_Loans_View.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        # ✅ --- END OF NEW CODE ---

        # show schedule for selected loan
        loan_id = st.number_input("Show schedule for loan id", min_value=1, value=int(loans_df.iloc[0].id))
        if st.button("Show schedule"):
            r = pd.read_sql_query("SELECT * FROM loans WHERE id = ?", con, params=(loan_id,))
            if r.empty:
                st.warning("Loan id not found.")
            else:
                row = r.iloc[0]
                interest_upfront, disbursed, sched = build_schedule(row.principal, row.term_months, row.annual_rate, row.disbursed_date)
                st.write(f"interest_upfront: {interest_upfront}, disbursed: {disbursed}")
                st.dataframe(sched)
                # show repayments
                repayments = pd.read_sql_query("SELECT payment_date, amount FROM repayments WHERE loan_id = ?", con, params=(loan_id,))
                st.write("Repayments:")
                st.dataframe(repayments)
