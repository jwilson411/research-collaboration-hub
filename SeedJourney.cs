// Entirely fictional demonstration of a documentation-methods study; no observations or participant data.
public static class SeedJourney
{
    public static State Apply(State state)
    {
        var study=state.Studies.Single(s=>s.Id=="atlas");
        var first=DateTimeOffset.Parse("2026-09-10T09:00:00Z");
        var second=DateTimeOffset.Parse("2026-09-12T14:00:00Z");
        study.Items.AddRange([
            new("journey-guide-v1","document","Handoff checklist • first outline","Synthetic methods exercise: compare a narrative handoff with a structured checklist. Record purpose, evidence, owner and next action. This first outline did not include an explicit unresolved-question section.",null,null,1,"alex",first){DocumentVersion=new("journey-guide",null)},
            new("journey-guide-v2","document","Handoff checklist • working edition","Entirely synthetic documentation-methods pilot. Purpose: make study continuation understandable to a new collaborator. Handoff sections: scope and assumptions; exact working document versions; decisions and alternatives; responsible participants and next actions; unresolved questions. No patient data, observations or external approval are represented.",null,null,2,"alex",second){DocumentVersion=new("journey-guide","journey-guide-v1")},
            new("journey-decision","decision","Keep unresolved questions visible","Use a dedicated unresolved-question section rather than burying uncertainty in completed tasks. Alternative considered: a single narrative summary. Rationale: a new collaborator should distinguish agreed working guidance from open choices.",null,"journey-guide-v2",1,"lead",second),
            new("journey-question","discussion","What should a returning collaborator read first?","Open question: should orientation start with the current checklist or the last handoff snapshot? Casey will try the sequence using only this fictional workspace and record a recommendation.",null,"journey-guide-v2",1,"reviewer",second),
            new("journey-task","task","Rehearse the returning-collaborator walkthrough","Read the accepted working checklist, compare the earlier outline, and capture a handoff snapshot with the unresolved orientation question. This is a synthetic usability rehearsal, not a research result.",null,null,1,"alex",second){Task=new("reviewer","2026-10-15","Open",["journey-guide-v2","journey-decision","journey-question"],[])},
            new("journey-idea","idea","Put uncertainty beside the next action","A compact list could show each open question beside its responsible participant and linked decision. Discuss this idea before changing the working checklist.",null,"journey-guide-v2",1,"alex",second),
            new("journey-start","documentation","New or returning? Start with this synthetic journey","1. Read Handoff checklist • working edition in Document library. 2. Inspect its review history and earlier outline. 3. Read the decision and open orientation question in Tasks & decisions / Discussions. 4. Capture a handoff in Handoffs. 5. Update the task, then reopen the snapshot to see the original captured context. Riley is the synthetic study lead; Casey reviews; Alex authors. Workspace acceptance is not formal study approval.",null,"journey-guide-v2",1,"lead",second)
        ]);
        study.DocumentReviews["journey-guide-v1"]=new("Superseded",[
            new("Draft","Review","Synthetic fixture: outline ready for review.","alex",first.AddHours(1)),
            new("Review","Accepted","Synthetic fixture: use this outline for the documentation exercise only.","lead",first.AddHours(2)),
            new("Accepted","Superseded","Synthetic fixture: replace with edition containing explicit unresolved questions.","lead",second.AddHours(-1))]);
        study.DocumentReviews["journey-guide-v2"]=new("Accepted",[
            new("Draft","Review","Synthetic fixture: revised checklist adds open questions.","alex",second.AddMinutes(10)),
            new("Review","Accepted","Synthetic fixture: agreed working guidance, not formal research approval.","lead",second.AddMinutes(20))]);
        state.Audit.Add(new("lead","Seeded synthetic document journey with workspace acceptance history",study.Id,second.AddMinutes(20)));
        var content=new HandoffContent(study.Title,study.Summary,study.Stage,study.Revision,null,
            study.Items.Where(item=>item.Id.StartsWith("journey-",StringComparison.Ordinal)).ToList(),[],
            study.DocumentReviews.ToDictionary(pair=>pair.Key,pair=>pair.Value));
        var snapshot=new HandoffSnapshot("journey-handoff","Orientation handoff • synthetic example",
            "Fictional baseline: accepted checklist, rationale, responsible reviewer and unresolved orientation question. Create another capture after updating the task to compare the two points in time.",
            "lead",second.AddMinutes(30),"seed-only","seed-only",content,"");
        study.Handoffs.Add(snapshot with {Sha256=HandoffEndpoints.CaptureDigest(snapshot)});
        return state;
    }
}
