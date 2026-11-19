import { Link } from 'react-router-dom';
import { BrandMark } from './Art';

export function SiteFooterPublic() {
  return (
    <footer className="pub-footer">
      <div className="wrap">
        <div className="cols">
          <div>
            <div className="brand" style={{ color: '#fff' }}><BrandMark size={28} /><span>StudentBelongings Cover</span></div>
            <p>Affordable belongings protection for students, shown as an academic prototype.</p>
          </div>
          <nav aria-label="Product"><h3>Product</h3><ul><li><a href="/#plans">Coverage plans</a></li><li><a href="/#how">How it works</a></li><li><a href="/#faq">FAQ</a></li></ul></nav>
          <nav aria-label="Company"><h3>Company</h3><ul><li><Link to="/about">About</Link></li><li><Link to="/contact">Contact</Link></li></ul></nav>
          <nav aria-label="Legal"><h3>Legal</h3><ul><li><Link to="/privacy">Privacy Policy</Link></li><li><Link to="/terms">Terms and Conditions</Link></li><li><Link to="/disclaimer">Insurance Disclaimer</Link></li></ul></nav>
        </div>
        <p className="fine">StudentBelongings Cover is an academic prototype. It is not a licensed insurer and does not issue real insurance. Policies, payments and settlements are simulated. Prices and limits are sample values.</p>
      </div>
    </footer>
  );
}
